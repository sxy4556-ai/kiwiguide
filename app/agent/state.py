"""图的状态定义。

状态会被 checkpointer 序列化保存，所以检索结果和引用都存成普通 dict，不存自定义对象。
"""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite


class Grade(TypedDict):
    sufficient: bool  # 检索结果能否回答问题
    reason: str  # 不足的原因，重试时交给 rewrite 参考
    retry: bool  # 是否回到 rewrite 重试


class SubQuestion(TypedDict):
    question: str  # 子问题（中文），生成回答时提醒模型逐条覆盖
    query: str  # 英文检索词
    topic: str | None  # 子问题自己的主题；复合问题可能跨主题，不能共用一个过滤条件


class SubResult(TypedDict):
    index: int  # 子问题序号，合并时按它排序，结果与并行任务完成的先后无关
    results: list[dict]


class AgentState(TypedDict, total=False):
    # 跨轮保留
    messages: Annotated[list[AnyMessage], add_messages]  # 完整对话（提问、反问、回答）
    summary: str  # 被压缩掉的早期对话的摘要
    # 每轮重置（见 new_turn）
    question: str  # 本轮问题；用户回答反问后会拼上补充信息
    sub_questions: list[SubQuestion]  # 1–3 个，每个单独检索
    search_queries: list[str]  # 各子问题的检索词，重试时告诉 rewrite 上次用过什么
    scope: Literal["in_scope", "off_topic"]
    needs_referral: bool  # 涉及个案法律或移民建议，回答末尾要附转介说明
    clarification_question: str | None  # rewrite 认为需要反问时的问题
    clarified: bool  # 本轮已经反问过一次，不再反问
    sub_results: Annotated[list[SubResult], operator.add]  # 并行检索各自写入，用 Overwrite 清空
    retrieved: list[dict]  # 合并后的父块字段加 score，按相关度排序
    grade: Grade | None
    retries: int
    answer: str
    citations: list[dict]  # index、title、url、retrieved_at


def new_turn(question: str) -> dict:
    """一轮提问的输入：追加用户消息，并清空上一轮的中间结果。"""
    return {
        "messages": [HumanMessage(question)],
        "question": question,
        "sub_questions": [],
        "search_queries": [],
        "scope": "in_scope",
        "needs_referral": False,
        "clarification_question": None,
        "clarified": False,
        "sub_results": Overwrite([]),
        "retrieved": [],
        "grade": None,
        "retries": 0,
        "answer": "",
        "citations": [],
    }
