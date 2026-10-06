"""逐题运行朴素 RAG 或 Agent，记录检索结果和回答，再由 LLM 评判打分。

两种模式输出相同结构的结果，方便直接对比：
- retrieved_urls：放进提示词的父块对应的页面，按名次排列，用来算 hit@k 和 MRR
- answer：最终回答；faithfulness、correctness：评判分数（无法评判时为 None）
"""

import time
from statistics import mean

from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import ask, pending_clarification, resume
from app.agent.nodes import Search, dict_to_result
from app.eval.judge import judge_correctness, judge_faithfulness
from app.eval.metrics import reciprocal_rank, summarize
from app.rag.naive import answer_question, format_context
from app.retrieval.search import SearchResult

# 题目没有预设 clarify_reply、Agent 却反问时使用的回答
DEFAULT_CLARIFY_REPLY = "没有更多信息了，请按最常见的情况回答。"


def run_naive(question: dict, search: Search, llm, top_k: int) -> dict:
    """朴素基线：原问题直接检索，不改写、不按主题过滤，也不会反问。"""
    results = search(question["question"], top_k, None)
    answer = answer_question(question["question"], lambda _q: results, llm)
    return {"answer": answer.answer, "results": results, "clarification": None}


def run_agent(question: dict, graph: CompiledStateGraph, thread_id: str) -> dict:
    """Agent 反问时用题目里预设的 clarify_reply 回答并继续，评测的是反问之后的最终回答。"""
    state = ask(graph, question["question"], thread_id)
    clarification = pending_clarification(state)
    if clarification:
        reply = question.get("clarify_reply") or DEFAULT_CLARIFY_REPLY
        state = resume(graph, reply, thread_id)
    return {
        "answer": state["answer"],
        "results": [dict_to_result(d) for d in state.get("retrieved", [])],
        "clarification": clarification,
        "retries": state.get("retries", 0),
        "sub_questions": len(state.get("sub_questions", [])),
    }


def evaluate(question: dict, run, judge_llm) -> dict:
    """run 是无参函数，返回 run_naive / run_agent 的结果；这里计时、算检索指标并评判。"""
    start = time.perf_counter()
    out = run()
    elapsed = time.perf_counter() - start
    results: list[SearchResult] = out.pop("results")
    urls = [r.parent.url for r in results]
    # 没有检索到资料时回答是固定文字，没有可核对的依据，忠实度不评
    faith = (judge_faithfulness(judge_llm, question["question"], out["answer"],
                                format_context(results)) if results else None)
    correct = judge_correctness(judge_llm, question["question"], out["answer"],
                                question["key_points"])
    return {
        "id": question["id"], "lang": question["lang"], "topic": question["topic"],
        "type": question["type"], "question": question["question"],
        "gold_urls": question["gold_urls"], "retrieved_urls": urls,
        "rr": reciprocal_rank(urls, question["gold_urls"]),
        **out,
        "faithfulness": faith.score if faith else None,
        "faithfulness_reason": faith.reason if faith else None,
        "correctness": correct.score if correct else None,
        "correctness_reason": correct.reason if correct else None,
        "seconds": round(elapsed, 1),
    }


def _mean_score(rows: list[dict], key: str) -> float | None:
    scores = [r[key] for r in rows if r[key] is not None]
    return round(mean(scores), 3) if scores else None


def summarize_answers(rows: list[dict]) -> dict:
    """检索指标沿用 metrics.summarize；评判分数只对成功评判的题求平均，并记下评判了几题。"""
    if not rows:
        return {"n": 0}
    return {
        **summarize(rows),
        "faithfulness": _mean_score(rows, "faithfulness"),
        "faithfulness_n": sum(r["faithfulness"] is not None for r in rows),
        "correctness": _mean_score(rows, "correctness"),
        "correctness_n": sum(r["correctness"] is not None for r in rows),
        "clarified": sum(bool(r["clarification"]) for r in rows),
        "avg_seconds": round(mean(r["seconds"] for r in rows), 1),
    }
