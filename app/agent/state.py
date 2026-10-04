"""图的状态定义。

状态会被 checkpointer 序列化保存，所以检索结果和引用都存成普通 dict，不存自定义对象。
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages


class Grade(TypedDict):
    sufficient: bool  # 检索结果能否回答问题
    reason: str  # 不足的原因，重试时交给 rewrite 参考
    retry: bool  # 是否回到 rewrite 重试


class AgentState(TypedDict, total=False):
    # 跨轮保留
    messages: Annotated[list[AnyMessage], add_messages]  # 完整对话（用户提问和最终回答）
    summary: str  # 被压缩掉的早期对话的摘要
    # 每轮重置（见 new_turn）
    question: str
    search_queries: list[str]
    topic: str | None
    retrieved: list[dict]  # 父块字段加 score，按相关度排序
    grade: Grade | None
    retries: int
    answer: str
    citations: list[dict]  # index、title、url、retrieved_at


def new_turn(question: str) -> dict:
    """一轮提问的输入：追加用户消息，并清空上一轮的中间结果。"""
    return {
        "messages": [HumanMessage(question)],
        "question": question,
        "search_queries": [],
        "topic": None,
        "retrieved": [],
        "grade": None,
        "retries": 0,
        "answer": "",
        "citations": [],
    }
