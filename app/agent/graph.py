"""组装 Agent 状态图，并用 SQLite checkpointer 按 thread_id 保存多轮会话。"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.nodes import DEFAULT_TOP_K, AgentNodes, Search, route_after_grade
from app.agent.state import AgentState, new_turn


def build_graph(
    llm,
    search: Search,
    checkpointer: BaseCheckpointSaver | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> CompiledStateGraph:
    """反问依赖 interrupt()，需要传入 checkpointer 才能在用户回答后从断点继续。"""
    nodes = AgentNodes(llm, search, top_k)
    graph = StateGraph(AgentState)
    graph.add_node("summarize", nodes.summarize)
    graph.add_node("rewrite", nodes.rewrite)
    # clarify 用 Command 决定去向：rewrite（反问后）、generate（越界）或并行的 retrieve
    graph.add_node("clarify", nodes.clarify, destinations=("rewrite", "retrieve", "generate"))
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("merge", nodes.merge)
    graph.add_node("grade", nodes.grade)
    graph.add_node("generate", nodes.generate)
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "rewrite")
    graph.add_edge("rewrite", "clarify")
    graph.add_edge("retrieve", "merge")  # 所有并行的 retrieve 完成后才执行 merge
    graph.add_edge("merge", "grade")
    graph.add_conditional_edges("grade", route_after_grade, ["rewrite", "generate"])
    graph.add_edge("generate", END)
    return graph.compile(checkpointer=checkpointer)


def open_checkpointer(path: Path) -> SqliteSaver:
    """打开会话库（通常是 `data/checkpoints.sqlite`）；用完后调用 `saver.conn.close()`。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def pending_clarification(state: dict) -> str | None:
    """图因反问暂停时返回反问内容，否则返回 None。"""
    interrupts = state.get("__interrupt__")
    return str(interrupts[0].value) if interrupts else None


def ask(graph: CompiledStateGraph, question: str, thread_id: str) -> dict:
    """在指定会话中提一个问题，返回本轮的状态（answer、citations 等）。

    需要反问时图会暂停，用 `pending_clarification()` 取出反问，再调用 `resume()` 继续。
    """
    return graph.invoke(new_turn(question), {"configurable": {"thread_id": thread_id}})


def resume(graph: CompiledStateGraph, reply: str, thread_id: str) -> dict:
    """提交用户对反问的回答，从断点继续执行。"""
    return graph.invoke(Command(resume=reply), {"configurable": {"thread_id": thread_id}})
