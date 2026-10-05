"""接口测试：用假模型和假检索器组装真实的 Agent 图，经 httpx AsyncClient 调用接口，不访问网络。

一轮问答中模型的调用顺序是 rewrite → grade → generate；反问时在 rewrite 之后暂停。
"""

import json
import threading

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.main as main_module
from app.agent.graph import build_graph
from app.api.service import STREAM_ERROR, ChatService
from app.ingest.chunk import Chunk
from app.rag.naive import DISCLAIMER
from app.retrieval.search import SearchResult
from tests.fakes import FakeChatModel, FakeSearcher

BOND = SearchResult(
    Chunk("p1", "p1", "https://www.tenancy.govt.nz/bond", "Bond", "tenancy", ["Bond"],
          "2026-10-02T03:00:00+00:00", "押金最多四周租金"),
    1.0,
)
SOURCES = [{"topic": "tenancy", "title": "Bond", "url": BOND.parent.url,
            "retrieved_at": "2026-10-02"}]


def rewrite_reply(query: str = "bond amount", **extra) -> str:
    subs = [{"question": "押金上限", "query": query, "topic": "tenancy"}]
    return json.dumps({"sub_questions": subs, **extra}, ensure_ascii=False)


GRADE_OK = json.dumps({"sufficient": True, "reason": ""})
ANSWER = "押金（bond）最多四周租金 [1]。"


def make_service(llm, refresh=lambda: "完成") -> ChatService:
    graph = build_graph(llm, FakeSearcher(default=[BOND]), InMemorySaver())
    return ChatService(graph, lambda: SOURCES, refresh)


def client_for(service_factory) -> httpx.AsyncClient:
    app = main_module.create_app(service_factory)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name and data:
            events.append((name, json.loads(data)))
    return events


async def test_chat_returns_answer_with_matching_citations():
    """/chat 必须返回完整回答和与正文编号对应的引用：前端靠 citations 渲染出处卡片，
    对不上就等于给了用户错误的出处。不传 thread_id 时要新建会话并返回它，否则无法继续追问。"""
    service = make_service(FakeChatModel([rewrite_reply(), GRADE_OK, ANSWER]))
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat", json={"question": "押金最多多少？"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert data["thread_id"]
    assert data["answer"].startswith(ANSWER)
    assert data["answer"].endswith(DISCLAIMER)
    assert data["citations"] == [{"index": 1, "title": "Bond", "url": BOND.parent.url,
                                  "retrieved_at": "2026-10-02"}]
    assert data["clarification_question"] is None


async def test_clarification_then_resume_in_same_thread():
    """缺少关键信息时 /chat 必须返回 needs_clarification 和反问，而不是硬答；
    用户通过 resume 回答后要在同一会话里从断点继续，并把补充信息带进检索和回答。"""
    llm = FakeChatModel([
        rewrite_reply(clarification="请问你是正式租客、合租房客还是寄宿？"),
        rewrite_reply("boarder rent increase"),
        GRADE_OK,
        ANSWER,
    ])
    service = make_service(llm)
    async with client_for(lambda: service) as client:
        first = (await client.post("/chat", json={"question": "涨租我有什么权利？",
                                                  "thread_id": "t-1"})).json()
        assert first == {"thread_id": "t-1", "status": "needs_clarification", "answer": None,
                         "citations": [],
                         "clarification_question": "请问你是正式租客、合租房客还是寄宿？"}
        resp = await client.post("/chat/t-1/resume", json={"answer": "寄宿"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "answered"
    assert resp.json()["answer"].startswith(ANSWER)
    # 恢复后的改写拿到了补充信息
    assert "补充信息：寄宿" in llm.calls[1][-1].content


async def test_resume_without_pending_question_is_409():
    """没有待回答反问的会话不能恢复：否则图会从空状态重跑，返回和提问无关的结果。
    错误信息必须是中文，前端直接展示给用户。"""
    service = make_service(FakeChatModel([]))
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat/unknown/resume", json={"answer": "学生签证"})
    assert resp.status_code == 409
    assert "没有等待回答的反问" in resp.json()["detail"]


async def test_invalid_requests_get_chinese_422():
    """空问题和非法会话 ID 必须在进入 Agent 前被拒绝，并用中文说明哪个字段有问题；
    空问题如果放进去会白白调用一次模型。"""
    service = make_service(FakeChatModel([]))
    async with client_for(lambda: service) as client:
        empty = await client.post("/chat", json={"question": "   "})
        bad_thread = await client.post("/chat", json={"question": "押金", "thread_id": "a/b"})
        bad_path = await client.post("/chat/a%20b/resume", json={"answer": "x"})
    assert empty.status_code == 422
    assert empty.json()["detail"] == "请求参数不合法：question"
    assert bad_thread.status_code == 422
    assert "thread_id" in bad_thread.json()["detail"]
    assert bad_path.status_code == 422


async def test_stream_sends_progress_answer_then_citations():
    """流式接口的事件顺序是前端渲染的约定：先给 thread_id（反问后要用它恢复），
    再推送节点进度，最后给完整回答和引用列表。
    完整回答必须与 /chat 一致，包含整理后的编号和免责声明。"""
    service = make_service(FakeChatModel([rewrite_reply(), GRADE_OK, ANSWER]))
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat/stream", json={"question": "押金最多多少？",
                                                       "thread_id": "s-1"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names[0] == "start" and events[0][1] == {"thread_id": "s-1"}
    progress = [d["node"] for n, d in events if n == "progress"]
    assert progress == ["summarize", "rewrite", "retrieve", "merge", "grade", "generate"]
    assert names[-3:] == ["answer", "citations", "done"]
    answer = dict(events)["answer"]["answer"]
    assert answer.startswith(ANSWER) and answer.endswith(DISCLAIMER)
    assert dict(events)["citations"]["citations"][0]["url"] == BOND.parent.url


async def test_stream_tokens_only_from_generate():
    """token 事件只能来自 generate：rewrite 和 grade 的输出是给程序看的 JSON，
    推给前端会在聊天框里闪过一段 JSON。"""
    llm = GenericFakeChatModel(messages=iter([
        AIMessage(rewrite_reply()), AIMessage(GRADE_OK), AIMessage(ANSWER),
    ]))
    service = make_service(llm)
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat/stream", json={"question": "押金最多多少？"})
    tokens = "".join(d["text"] for n, d in parse_sse(resp.text) if n == "token")
    assert tokens == ANSWER
    assert "sub_questions" not in tokens


async def test_stream_clarification_event():
    """流式提问遇到反问时必须发送 clarification 而不是 answer，前端据此显示回答框。"""
    llm = FakeChatModel([rewrite_reply(clarification="请问是学期中还是假期？")])
    service = make_service(llm)
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat/stream", json={"question": "每周能打多少小时工？"})
    events = parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "answer" not in names
    clarification = dict(events)["clarification"]
    assert clarification["clarification_question"] == "请问是学期中还是假期？"
    assert dict(events)["done"]["status"] == "needs_clarification"


async def test_stream_error_event_instead_of_broken_connection():
    """模型调用出错时，流式接口必须发送中文的 error 事件：响应头已经是 200，
    直接断开连接的话前端只能看到一个没有说明的空回答。"""
    service = make_service(FakeChatModel([]))  # 没有编排回复，第一次调用就会报错
    async with client_for(lambda: service) as client:
        resp = await client.post("/chat/stream", json={"question": "押金最多多少？"})
    events = parse_sse(resp.text)
    assert events[-1] == ("error", {"detail": STREAM_ERROR})


async def test_sources_lists_indexed_pages():
    """/sources 让用户知道助手依据了哪些官方页面，字段要齐全（主题、标题、链接、抓取日期）。"""
    service = make_service(FakeChatModel([]))
    async with client_for(lambda: service) as client:
        resp = await client.get("/sources")
    assert resp.status_code == 200
    assert resp.json() == {"total": 1, "sources": SOURCES}


async def test_refresh_runs_in_background_and_rejects_duplicates():
    """重新抓取要几分钟，必须在后台运行并立即返回 202；同时只能有一个任务，
    否则两个任务会同时写同一个索引。完成后要能查到结果摘要。"""
    release = threading.Event()

    def slow_refresh() -> str:
        release.wait(5)
        return "抓取 3 个来源：成功 3"

    service = make_service(FakeChatModel([]), refresh=slow_refresh)
    async with client_for(lambda: service) as client:
        first = await client.post("/ingest/refresh")
        second = await client.post("/ingest/refresh")
        release.set()
        service.refresh_job.join(5)
        status = (await client.get("/ingest/refresh")).json()
    assert first.status_code == 202
    assert first.json()["status"] == "running"
    assert second.status_code == 409
    assert "已经在运行" in second.json()["detail"]
    assert status["status"] == "succeeded"
    assert status["message"] == "抓取 3 个来源：成功 3"
    assert status["finished_at"]


async def test_refresh_failure_reported_in_status():
    """后台任务失败不能让服务崩溃，原因要记在状态里，否则用户只会看到任务一直不结束。"""

    def broken() -> str:
        raise RuntimeError("sources.yaml 不存在")

    service = make_service(FakeChatModel([]), refresh=broken)
    async with client_for(lambda: service) as client:
        await client.post("/ingest/refresh")
        service.refresh_job.join(5)
        status = (await client.get("/ingest/refresh")).json()
    assert status["status"] == "failed"
    assert "sources.yaml 不存在" in status["message"]


async def test_service_unavailable_is_503_but_health_still_works(monkeypatch):
    """Ollama 没启动或索引没建时，问答接口返回中文的 503；/health 和首页不依赖问答服务，
    必须照常可用，用户才能看到页面并得知原因。"""

    async def fake_check(base_url: str) -> bool:
        return False

    def broken_factory():
        raise ConnectionError("ollama down")

    monkeypatch.setattr(main_module, "check_ollama", fake_check)
    async with client_for(broken_factory) as client:
        chat = await client.post("/chat", json={"question": "押金最多多少？"})
        health = await client.get("/health")
        index = await client.get("/")
    assert chat.status_code == 503
    assert "Ollama" in chat.json()["detail"]
    assert health.status_code == 200 and health.json()["status"] == "degraded"
    assert index.status_code == 200


async def test_unknown_path_is_chinese_404():
    """所有错误统一返回中文的 detail，前端不用区分错误来源。"""
    async with client_for(lambda: make_service(FakeChatModel([]))) as client:
        resp = await client.get("/no-such-api")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "接口不存在"}


async def test_index_page_has_key_chinese_elements():
    """首页是用户唯一的入口：必须有免责声明、四个主题的快捷问题，并调用流式和恢复接口。"""
    async with client_for(lambda: make_service(FakeChatModel([]))) as client:
        resp = await client.get("/")
        docs = await client.get("/docs")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    for text in ["免责声明", "租房", "打工", "签证", "税务", "/chat/stream", "/resume", "抓取于"]:
        assert text in html
    assert docs.status_code == 200
