"""组装 Agent 状态图，并用 SQLite checkpointer 按 thread_id 保存多轮会话。"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes import DEFAULT_TOP_K, AgentNodes, Search, route_after_grade
from app.agent.state import AgentState, new_turn


def build_graph(
    llm,
    search: Search,
    checkpointer: BaseCheckpointSaver | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> CompiledStateGraph:
    nodes = AgentNodes(llm, search, top_k)
    graph = StateGraph(AgentState)
    graph.add_node("summarize", nodes.summarize)
    graph.add_node("rewrite", nodes.rewrite)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade", nodes.grade)
    graph.add_node("generate", nodes.generate)
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "rewrite")
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade, ["rewrite", "generate"])
    graph.add_edge("generate", END)
    return graph.compile(checkpointer=checkpointer)


def open_checkpointer(path: Path) -> SqliteSaver:
    """打开会话库（通常是 `data/checkpoints.sqlite`）；用完后调用 `saver.conn.close()`。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def ask(graph: CompiledStateGraph, question: str, thread_id: str) -> dict:
    """在指定会话中提一个问题，返回本轮结束后的完整状态（answer、citations 等）。"""
    return graph.invoke(new_turn(question), {"configurable": {"thread_id": thread_id}})
