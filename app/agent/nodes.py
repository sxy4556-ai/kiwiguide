"""图中的各个节点。

summarize → rewrite → clarify →（需要反问时暂停，回答后回到 rewrite；越界时直接到 generate）
→ 每个子问题并行 retrieve → merge → grade →（不足时回到 rewrite）→ generate。
"""

import logging
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.types import Command, Overwrite, Send, interrupt
from pydantic import BaseModel, Field, field_validator, model_validator

from app.agent.prompts import (
    GENERATE_PROMPT,
    GENERATE_REFERRAL_NOTE,
    GENERATE_SUB_QUESTIONS_NOTE,
    GRADE_PROMPT,
    JSON_RETRY_PROMPT,
    OFF_TOPIC_ANSWER,
    REFERRAL_CONTACTS,
    REFERRAL_FALLBACK,
    REFERRAL_TEMPLATE,
    REWRITE_PROMPT,
    REWRITE_RETRY_NOTE,
    SUMMARIZE_PROMPT,
    TOPICS,
)
from app.agent.state import AgentState, SubQuestion
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
MAX_SUB_QUESTIONS = 3  # 复合问题最多拆成几个子问题

Search = Callable[[str, int, str | None], list[SearchResult]]

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_JSON_RE = re.compile(r"\{.*\}", re.S)
# 匹配 [1]、[1,3]、[1、3] 等引用写法；部分模型（如 gpt-oss）习惯用全角的【1】或［1］，
# 有时还会写成【[1]】，外层的【】一并匹配，替换后不留多余括号
_CITE_RE = re.compile(r"【?[\[【［](\d+(?:\s*[,，、]\s*\d+)*)[\]】］]】?")


class SubQuestionOutput(BaseModel):
    question: str = ""
    query: str = Field(min_length=1)
    topic: str | None = None

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, v):
        # 模型给出的主题不在四个之内时不过滤，避免用错误主题把正确页面滤掉
        v = str(v).strip().lower() if v is not None else None
        return v if v in TOPICS else None


class RewriteOutput(BaseModel):
    sub_questions: list[SubQuestionOutput] = []
    scope: Literal["in_scope", "off_topic"] = "in_scope"
    needs_referral: bool = False
    clarification: str | None = None

    @field_validator("sub_questions")
    @classmethod
    def _limit_sub_questions(cls, v: list[SubQuestionOutput]) -> list[SubQuestionOutput]:
        return [s for s in v if s.query.strip()][:MAX_SUB_QUESTIONS]

    @model_validator(mode="after")
    def _require_sub_questions(self):
        # 越界问题不检索，模型常给出空的子问题列表；范围内的问题至少要有一个子问题
        if self.scope == "in_scope" and not self.sub_questions:
            raise ValueError("sub_questions 不能为空")
        return self

    @field_validator("clarification", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return v.strip() or None if isinstance(v, str) else v


class RetrieveTask(TypedDict):
    """Send 发给 retrieve 的单个子问题。"""

    index: int
    query: str
    topic: str | None


class GradeOutput(BaseModel):
    sufficient: bool
    reason: str = ""


def strip_think(text: str) -> str:
    """去掉推理模型输出的思考段。

    除了成对的 <think>…</think>，还要处理只有结尾标签的情况：总是开启思考的模型版本
    把开头标签放在提示模板里，输出中只剩 </think>，这时取最后一个 </think> 之后的内容。
    """
    text = _THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


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


def referral_note(state: AgentState) -> str:
    """按子问题涉及的主题列出对应机构；同一机构只列一次，主题都未知时用通用说明。"""
    contacts = []
    for s in state.get("sub_questions", []):
        contact = REFERRAL_CONTACTS.get(s["topic"] or "")
        if contact and contact not in contacts:
            contacts.append(contact)
    return REFERRAL_TEMPLATE.format(contacts="；或".join(contacts) or REFERRAL_FALLBACK)


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
            # 降级：原问题直接检索，不按主题过滤，相当于朴素 RAG；不反问、不拒答
            fallback = SubQuestionOutput(question=question, query=question)
            out = RewriteOutput(sub_questions=[fallback])
        subs = [SubQuestion(question=s.question or question, query=s.query.strip(), topic=s.topic)
                for s in out.sub_questions]
        return {
            "sub_questions": subs,
            "search_queries": [s["query"] for s in subs],
            "scope": out.scope,
            "needs_referral": out.needs_referral,
            "clarification_question": out.clarification,
            "sub_results": Overwrite([]),  # 重试时清掉上一次的检索结果
        }

    def clarify(self, state: AgentState) -> Command[Literal["rewrite", "retrieve", "generate"]]:
        """决定下一步：反问、拒答，或把每个子问题并行发给 retrieve。

        反问和拒答只在第一次改写后考虑：重试时问题已经确认在范围内，不应再打断用户。
        每轮最多反问一次，避免模型反复追问。
        """
        first_pass = state.get("retries", 0) == 0
        question = state.get("clarification_question")
        if first_pass and question and not state.get("clarified"):
            # 暂停整张图，把反问交给调用方；恢复时 interrupt() 返回用户的回答，本节点从头重跑
            reply = str(interrupt(question)).strip()
            return Command(goto="rewrite", update={
                "question": f"{state['question']}\n补充信息：{reply}",
                "clarified": True,
                "messages": [AIMessage(question), HumanMessage(reply)],
            })
        if first_pass and state.get("scope") == "off_topic":
            return Command(goto="generate")
        return Command(goto=[
            Send("retrieve", RetrieveTask(index=i, query=s["query"], topic=s["topic"]))
            for i, s in enumerate(state["sub_questions"])
        ])

    def retrieve(self, task: RetrieveTask) -> dict:
        """检索一个子问题；多个子问题由 Send 并行执行，各自往 sub_results 追加一项。"""
        results = self.search(task["query"], self.top_k, task["topic"])
        return {"sub_results": [{"index": task["index"],
                                 "results": [result_to_dict(r) for r in results]}]}

    def merge(self, state: AgentState) -> dict:
        """各子问题的结果按名次交替合并、按父块去重，最多保留 top_k 个。

        交替合并保证每个子问题都至少有一个父块进入上下文，这正是拆分的目的。
        """
        rankings = [s["results"] for s in sorted(state["sub_results"], key=lambda s: s["index"])]
        merged: list[dict] = []
        seen: set[str] = set()
        for rank in range(max((len(r) for r in rankings), default=0)):
            for ranking in rankings:
                if rank < len(ranking) and ranking[rank]["id"] not in seen:
                    seen.add(ranking[rank]["id"])
                    merged.append(ranking[rank])
        return {"retrieved": merged[: self.top_k]}

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
        if state.get("scope") == "off_topic" and not state.get("retrieved"):
            # 越界问题不检索也不调用模型，固定文字拒答
            return {"answer": OFF_TOPIC_ANSWER, "citations": [],
                    "messages": [AIMessage(OFF_TOPIC_ANSWER)]}
        results = [dict_to_result(d) for d in state["retrieved"]]
        referral = referral_note(state) if state.get("needs_referral") else ""
        if not results:
            # 没有资料时不调用模型，避免模型凭记忆编造
            answer = "\n\n".join(p for p in (NO_RESULT_ANSWER, referral, DISCLAIMER) if p)
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
        subs = state.get("sub_questions", [])
        if len(subs) > 1:
            items = "\n".join(f"{i}. {s['question']}" for i, s in enumerate(subs, 1))
            parts.append(GENERATE_SUB_QUESTIONS_NOTE.format(items=items))
        if referral:
            parts.append(GENERATE_REFERRAL_NOTE)
        parts.append(f"问题：{state['question']}")
        reply = strip_think(
            self.llm.invoke([SystemMessage(GENERATE_PROMPT), HumanMessage("\n\n".join(parts))])
            .content
        )
        body, citations = renumber_citations(reply, results)
        answer = "\n\n".join(
            p for p in (body, format_sources(citations), referral, DISCLAIMER) if p
        )
        return {
            "answer": answer,
            "citations": [asdict(c) for c in citations],
            "messages": [AIMessage(answer)],
        }


def route_after_grade(state: AgentState) -> str:
    return "rewrite" if state["grade"]["retry"] else "generate"
