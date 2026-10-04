"""图中的各个节点：summarize → rewrite → retrieve → grade →（不足时回到 rewrite）→ generate。"""

import logging
import re
from collections.abc import Callable
from dataclasses import asdict

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from app.agent.prompts import (
    GENERATE_PROMPT,
    GRADE_PROMPT,
    JSON_RETRY_PROMPT,
    REWRITE_PROMPT,
    REWRITE_RETRY_NOTE,
    SUMMARIZE_PROMPT,
    TOPICS,
)
from app.agent.state import AgentState
from app.ingest.chunk import Chunk
from app.rag.naive import DISCLAIMER, NO_RESULT_ANSWER, Citation, format_context, format_sources
from app.retrieval.search import SearchResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # grade 判定不足时最多回到 rewrite 的次数
SUMMARY_AFTER_ROUNDS = 6  # 已完成的问答超过这个轮数就压缩历史
KEEP_MESSAGES = 5  # 压缩后保留的最近消息：两轮问答加当前问题
HISTORY_MESSAGES = 4  # 改写和生成时附带的最近消息条数
HISTORY_CHARS = 600  # 每条历史消息截取的长度，避免旧回答占满上下文
DEFAULT_TOP_K = 6

Search = Callable[[str, int, str | None], list[SearchResult]]

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_JSON_RE = re.compile(r"\{.*\}", re.S)
# 匹配 [1]、[1,3]、[1、3] 等引用写法
_CITE_RE = re.compile(r"\[(\d+(?:\s*[,，、]\s*\d+)*)\]")


class RewriteOutput(BaseModel):
    queries: list[str] = Field(min_length=1)
    topic: str | None = None

    @field_validator("queries")
    @classmethod
    def _clean_queries(cls, v: list[str]) -> list[str]:
        v = [q.strip() for q in v if q.strip()][:3]
        if not v:
            raise ValueError("queries 不能为空")
        return v

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, v):
        # 模型给出的主题不在四个之内时不过滤，避免用错误主题把正确页面滤掉
        v = str(v).strip().lower() if v is not None else None
        return v if v in TOPICS else None


class GradeOutput(BaseModel):
    sufficient: bool
    reason: str = ""


def strip_think(text: str) -> str:
    """去掉推理模型输出的 <think>…</think> 段。"""
    return _THINK_RE.sub("", text).strip()


def parse_json[T: BaseModel](text: str, schema: type[T]) -> T:
    """从模型输出中取出第一个 {...} 并校验；模型常在 JSON 外包一层 ```json 或说明文字。"""
    match = _JSON_RE.search(strip_think(text))
    if not match:
        raise ValueError("输出中没有 JSON 对象")
    return schema.model_validate_json(match.group(0))


def invoke_json[T: BaseModel](llm, messages: list, schema: type[T]) -> T | None:
    """调用模型并解析 JSON；失败时把错误告诉模型重试一次，仍失败返回 None，由调用方降级。"""
    reply = llm.invoke(messages).content
    try:
        return parse_json(reply, schema)
    except ValueError as e:  # pydantic 的 ValidationError 也是 ValueError
        error = str(e).splitlines()[0]
    retry = [*messages, AIMessage(reply), HumanMessage(JSON_RETRY_PROMPT.format(error=error))]
    try:
        return parse_json(llm.invoke(retry).content, schema)
    except ValueError as e:
        logger.warning("%s 解析两次均失败，走降级逻辑：%s", schema.__name__, str(e).splitlines()[0])
        return None


def result_to_dict(r: SearchResult) -> dict:
    return {**asdict(r.parent), "score": r.score}


def dict_to_result(d: dict) -> SearchResult:
    fields = {k: v for k, v in d.items() if k != "score"}
    return SearchResult(Chunk(**fields), d["score"])


def renumber_citations(text: str, results: list[SearchResult]) -> tuple[str, list[Citation]]:
    """把正文中的 [n] 按首次出现的顺序重新编号为 1、2、3…，只保留实际引用过的来源。

    越界编号（资料里没有对应来源）直接删掉，保证正文的每个编号都能在来源列表中找到。
    模型完全没有标注引用时，把全部资料列为来源，编号保持不变。
    """
    mapping: dict[int, int] = {}

    def repl(m: re.Match) -> str:
        out = []
        for part in re.split(r"\s*[,，、]\s*", m.group(1)):
            n = int(part)
            if not 1 <= n <= len(results):
                continue
            mapping.setdefault(n, len(mapping) + 1)
            out.append(f"[{mapping[n]}]")
        return "".join(out)

    body = _CITE_RE.sub(repl, text)
    if not mapping:
        mapping = {i: i for i in range(1, len(results) + 1)}
    citations = []
    for old, new in sorted(mapping.items(), key=lambda kv: kv[1]):
        p = results[old - 1].parent
        citations.append(Citation(new, p.title, p.url, p.retrieved_at[:10]))
    return body, citations


def format_history(state: AgentState) -> str:
    """摘要加最近几条消息（不含当前问题），供改写和生成理解指代。"""
    parts = []
    if state.get("summary"):
        parts.append(f"早期对话摘要：{state['summary']}")
    for m in state["messages"][:-1][-HISTORY_MESSAGES:]:
        role = "用户" if m.type == "human" else "助手"
        parts.append(f"{role}：{m.content[:HISTORY_CHARS]}")
    return "\n".join(parts)


class AgentNodes:
    def __init__(self, llm, search: Search, top_k: int = DEFAULT_TOP_K):
        self.llm = llm
        self.search = search
        self.top_k = top_k

    def summarize(self, state: AgentState) -> dict:
        messages = state["messages"]
        finished_rounds = sum(1 for m in messages if m.type == "human") - 1
        if finished_rounds <= SUMMARY_AFTER_ROUNDS:
            return {}
        old = messages[:-KEEP_MESSAGES]
        lines = [f"{'用户' if m.type == 'human' else '助手'}：{m.content}" for m in old]
        if state.get("summary"):
            lines.insert(0, f"更早的摘要：{state['summary']}")
        try:
            summary = strip_think(
                self.llm.invoke([SystemMessage(SUMMARIZE_PROMPT), HumanMessage("\n".join(lines))])
                .content
            )
        except Exception:  # 摘要不是必需步骤，失败时保留原历史继续回答
            logger.warning("对话摘要失败，本轮不压缩历史", exc_info=True)
            return {}
        if not summary:
            return {}
        return {"summary": summary, "messages": [RemoveMessage(id=m.id) for m in old]}

    def rewrite(self, state: AgentState) -> dict:
        question = state["question"]
        parts = []
        history = format_history(state)
        if history:
            parts.append(f"对话背景：\n{history}")
        parts.append(f"最新问题：{question}")
        grade = state.get("grade")
        if grade and grade["retry"]:
            parts.append(REWRITE_RETRY_NOTE.format(
                queries="；".join(state.get("search_queries", [])), reason=grade["reason"]
            ))
        out = invoke_json(
            self.llm, [SystemMessage(REWRITE_PROMPT), HumanMessage("\n\n".join(parts))],
            RewriteOutput,
        )
        if out is None:
            # 降级：原问题直接检索，不按主题过滤，相当于朴素 RAG
            return {"search_queries": [question], "topic": None}
        return {"search_queries": out.queries, "topic": out.topic}

    def retrieve(self, state: AgentState) -> dict:
        """每条检索词分别检索，按名次交替合并、按父块去重，最多保留 top_k 个。"""
        rankings = [self.search(q, self.top_k, state.get("topic")) for q in state["search_queries"]]
        merged: list[SearchResult] = []
        seen: set[str] = set()
        for rank in range(max((len(r) for r in rankings), default=0)):
            for ranking in rankings:
                if rank < len(ranking) and ranking[rank].parent.id not in seen:
                    seen.add(ranking[rank].parent.id)
                    merged.append(ranking[rank])
        return {"retrieved": [result_to_dict(r) for r in merged[: self.top_k]]}

    def grade(self, state: AgentState) -> dict:
        results = [dict_to_result(d) for d in state["retrieved"]]
        retries = state.get("retries", 0)
        if not results:
            sufficient, reason = False, "没有检索到任何资料"
        else:
            out = invoke_json(
                self.llm,
                [SystemMessage(GRADE_PROMPT),
                 HumanMessage(f"问题：{state['question']}\n\n资料：\n\n{format_context(results)}")],
                GradeOutput,
            )
            if out is None:
                # 降级：评估结果无法解析时不再重试，直接用现有资料作答
                sufficient, reason = True, "评估结果无法解析"
            else:
                sufficient, reason = out.sufficient, out.reason
        retry = not sufficient and retries < MAX_RETRIES
        return {
            "grade": {"sufficient": sufficient, "reason": reason, "retry": retry},
            "retries": retries + 1 if retry else retries,
        }

    def generate(self, state: AgentState) -> dict:
        results = [dict_to_result(d) for d in state["retrieved"]]
        if not results:
            # 没有资料时不调用模型，避免模型凭记忆编造
            answer = f"{NO_RESULT_ANSWER}\n\n{DISCLAIMER}"
            return {"answer": answer, "citations": [], "messages": [AIMessage(answer)]}
        parts = []
        history = format_history(state)
        if history:
            parts.append(f"对话背景：\n{history}")
        parts.append(f"资料：\n\n{format_context(results)}")
        grade = state.get("grade")
        if grade and not grade["sufficient"]:
            parts.append(f"（注意：资料可能不足以完整回答，原因：{grade['reason']}。"
                         "资料没有覆盖的部分请明确说明。）")
        parts.append(f"问题：{state['question']}")
        reply = strip_think(
            self.llm.invoke([SystemMessage(GENERATE_PROMPT), HumanMessage("\n\n".join(parts))])
            .content
        )
        body, citations = renumber_citations(reply, results)
        answer = f"{body}\n\n{format_sources(citations)}\n\n{DISCLAIMER}"
        return {
            "answer": answer,
            "citations": [asdict(c) for c in citations],
            "messages": [AIMessage(answer)],
        }


def route_after_grade(state: AgentState) -> str:
    return "rewrite" if state["grade"]["retry"] else "generate"
