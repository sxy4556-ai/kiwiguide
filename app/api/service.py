"""接口背后的服务：包装 Agent 的提问、反问恢复、流式输出，以及来源列表和后台更新任务。

Agent 和存储都是同步代码，由接口层放进线程池执行，不阻塞事件循环。
"""

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import ask, build_graph, open_checkpointer, pending_clarification, resume
from app.agent.state import new_turn
from app.config import Settings
from app.ingest.fetch import Fetcher
from app.ingest.index import build_index, load_processed
from app.ingest.refresh import describe_refresh, fetch_sources
from app.ingest.sources import load_sources
from app.llm import get_chat_model
from app.retrieval.embeddings import make_dense_embedder, make_sparse_embedder, probe_dimension
from app.retrieval.search import HybridSearcher
from app.retrieval.store import ParentStore, VectorStore

logger = logging.getLogger(__name__)

# 流式输出时推送给前端的节点进度；clarify 只做路由，不单独提示
NODE_LABELS = {
    "summarize": "正在整理对话历史",
    "rewrite": "正在理解问题、生成检索词",
    "retrieve": "正在检索官方资料",
    "merge": "正在合并检索结果",
    "grade": "正在评估资料是否足够",
    "generate": "正在生成回答",
}
STREAM_ERROR = "生成回答时出错，请稍后再试"


class ServiceError(Exception):
    """可以预期的业务错误，接口层按 status_code 返回中文的 detail。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def new_thread_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_response(thread_id: str, state: dict) -> dict:
    """把一轮的图状态转换成 ChatResponse 的字段。"""
    question = pending_clarification(state)
    if question:
        return {"thread_id": thread_id, "status": "needs_clarification",
                "answer": None, "citations": [], "clarification_question": question}
    return {"thread_id": thread_id, "status": "answered", "answer": state["answer"],
            "citations": state.get("citations", []), "clarification_question": None}


class RefreshJob:
    """后台更新任务：同一时间只运行一个，状态可随时查询。"""

    def __init__(self, run: Callable[[], str]):
        self._run = run  # 执行抓取和建索引，返回中文的结果摘要
        self._lock = threading.Lock()
        self._status = {"status": "idle", "started_at": None, "finished_at": None, "message": ""}
        self._thread: threading.Thread | None = None

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self) -> bool:
        """启动任务；已经在运行时不重复启动，返回 False。"""
        with self._lock:
            if self._status["status"] == "running":
                return False
            self._status = {"status": "running", "started_at": _now(), "finished_at": None,
                            "message": "正在重新抓取并更新索引"}
            self._thread = threading.Thread(target=self._work, name="ingest-refresh", daemon=True)
            self._thread.start()
        return True

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _work(self) -> None:
        try:
            status, message = "succeeded", self._run()
        except Exception as e:  # 任务失败只记录在状态里，不影响服务
            logger.exception("更新索引失败")
            status, message = "failed", f"更新失败：{e}"
        with self._lock:
            self._status.update(status=status, finished_at=_now(), message=message)


class ChatService:
    def __init__(
        self,
        graph: CompiledStateGraph,
        list_sources: Callable[[], list[dict]],
        refresh: Callable[[], str],
        close: Callable[[], None] | None = None,
    ):
        self.graph = graph
        self._list_sources = list_sources
        self.refresh_job = RefreshJob(refresh)
        self._close = close

    def close(self) -> None:
        if self._close:
            self._close()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def chat(self, question: str, thread_id: str | None = None) -> dict:
        thread_id = thread_id or new_thread_id()
        return build_response(thread_id, ask(self.graph, question, thread_id))

    def resume(self, thread_id: str, answer: str) -> dict:
        if not self.graph.get_state(self._config(thread_id)).interrupts:
            # 没有暂停的会话不能恢复：否则图会从空状态重跑，给出与提问无关的结果
            raise ServiceError(409, "这个会话没有等待回答的反问，请直接提问")
        return build_response(thread_id, resume(self.graph, answer, thread_id))

    def stream(self, question: str, thread_id: str | None = None) -> Iterator[tuple[str, dict]]:
        """依次产出 (事件名, 数据)：start、progress、token、answer、citations、done。

        token 是 generate 节点的原始输出，只用于边生成边显示；引用编号整理、来源列表和
        免责声明在节点结束后才加上，所以最后的 answer 事件给出完整回答，前端用它替换已显示的文字。
        需要反问时以 clarification 事件代替 answer 和 citations。出错时发送 error 事件后结束。
        """
        thread_id = thread_id or new_thread_id()
        config = self._config(thread_id)
        yield "start", {"thread_id": thread_id}
        try:
            for mode, chunk in self.graph.stream(
                new_turn(question), config, stream_mode=["updates", "messages"]
            ):
                if mode == "updates":
                    for node in chunk:
                        if node in NODE_LABELS:
                            yield "progress", {"node": node, "label": NODE_LABELS[node]}
                    continue
                message, meta = chunk
                if (meta.get("langgraph_node") == "generate"
                        and isinstance(message, AIMessageChunk) and message.content):
                    yield "token", {"text": message.content}
            snapshot = self.graph.get_state(config)
        except Exception:
            logger.exception("流式回答失败：thread_id=%s", thread_id)
            yield "error", {"detail": STREAM_ERROR}
            return
        response = build_response(
            thread_id, {**snapshot.values, "__interrupt__": snapshot.interrupts}
        )
        if response["status"] == "needs_clarification":
            yield "clarification", response
        else:
            yield "answer", {"answer": response["answer"]}
            yield "citations", {"citations": response["citations"]}
        yield "done", {"thread_id": thread_id, "status": response["status"]}

    def sources(self) -> list[dict]:
        return self._list_sources()


def build_service(settings: Settings) -> ChatService:
    """用真实模型和本地索引创建服务。需要 Ollama 可用（探测向量维度）。

    Qdrant 本地库同一时间只允许一个进程打开，所以服务运行时不要再运行建索引或提问脚本，
    更新索引请用 `/ingest/refresh`。
    """
    dense, sparse = make_dense_embedder(settings), make_sparse_embedder(settings)
    vector_store = VectorStore.open(settings.data_dir / "qdrant", probe_dimension(dense))
    parent_store = ParentStore(settings.data_dir / "parents.sqlite")
    saver = open_checkpointer(settings.data_dir / "checkpoints.sqlite")
    searcher = HybridSearcher(vector_store, parent_store, dense, sparse)
    graph = build_graph(get_chat_model(settings), searcher.search, saver)

    def list_sources() -> list[dict]:
        with searcher.storage_lock:
            docs = parent_store.list_documents()
        return [{**d, "retrieved_at": (d["retrieved_at"] or "")[:10]} for d in docs]

    def refresh() -> str:
        fetcher = Fetcher()
        try:
            fetched = fetch_sources(load_sources(settings.sources_file), fetcher, settings.data_dir)
        finally:
            fetcher.close()
        docs = load_processed(settings.data_dir)
        # 写索引期间持有检索锁：本地 Qdrant 和 SQLite 不能同时读写，检索会等更新完成
        with searcher.storage_lock:
            stats = build_index(docs, vector_store, parent_store, dense, sparse)
        return describe_refresh(fetched, stats)

    def close() -> None:
        saver.conn.close()
        vector_store.close()
        parent_store.close()

    return ChatService(graph, list_sources, refresh, close)
