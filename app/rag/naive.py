"""朴素 RAG 基线：直接用原问题检索，把父块编号后拼进提示词，生成带 [n] 引用的中文回答。"""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from app.retrieval.search import SearchResult

SYSTEM_PROMPT = """你是新西兰留学生生活助手，只根据下面提供的官方资料回答问题。
要求：
1. 用中文回答；官方机构名和术语第一次出现时附英文原名，例如"押金（bond）"。
2. 每条结论后用 [编号] 标注出处，编号对应资料前的编号，例如 [1] 或 [1][3]。
3. 资料中没有的信息不要编造，直接说明资料里没有提到。"""

NO_RESULT_ANSWER = "没有检索到相关的官方资料，暂时无法回答这个问题。"
DISCLAIMER = "以上内容仅供参考，不构成法律、移民或税务建议，请以官方网站的最新信息为准。"


@dataclass
class Citation:
    index: int
    title: str
    url: str
    retrieved_at: str


@dataclass
class NaiveAnswer:
    answer: str
    citations: list[Citation]


def format_context(results: list[SearchResult]) -> str:
    """每个父块前加 [n] 编号和来源，编号从 1 开始，与引用列表一致。"""
    blocks = []
    for i, r in enumerate(results, 1):
        p = r.parent
        section = " > ".join(p.heading_path)
        header = f"[{i}] {p.title}" + (f"（{section}）" if section else "") + f"\n来源：{p.url}"
        blocks.append(f"{header}\n{p.text}")
    return "\n\n---\n\n".join(blocks)


def build_citations(results: list[SearchResult]) -> list[Citation]:
    return [
        Citation(i, r.parent.title, r.parent.url, r.parent.retrieved_at[:10])
        for i, r in enumerate(results, 1)
    ]


def format_sources(citations: list[Citation]) -> str:
    lines = [f"[{c.index}] {c.title} - {c.url}（抓取于 {c.retrieved_at}）" for c in citations]
    return "参考来源：\n" + "\n".join(lines)


def answer_question(
    question: str,
    search: Callable[[str], list[SearchResult]],
    llm,
) -> NaiveAnswer:
    results = search(question)
    if not results:
        # 没有资料时不调用模型，避免模型凭记忆编造
        return NaiveAnswer(f"{NO_RESULT_ANSWER}\n\n{DISCLAIMER}", [])
    messages = [
        SystemMessage(SYSTEM_PROMPT),
        HumanMessage(f"资料：\n\n{format_context(results)}\n\n问题：{question}"),
    ]
    reply = llm.invoke(messages).content.strip()
    citations = build_citations(results)
    return NaiveAnswer(f"{reply}\n\n{format_sources(citations)}\n\n{DISCLAIMER}", citations)
