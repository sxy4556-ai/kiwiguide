"""回答评测测试：评判输入、反问处理和分数汇总。全部用假模型，不访问网络。"""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_graph
from app.eval.judge import answer_body, judge_correctness
from app.eval.runner import evaluate, run_agent, run_naive, summarize_answers
from app.ingest.chunk import Chunk
from app.rag.naive import DISCLAIMER
from app.retrieval.search import SearchResult
from tests.fakes import FakeChatModel, FakeSearcher

BOND = SearchResult(Chunk("p1", "p1", "https://www.tenancy.govt.nz/bond", "Bond", "tenancy",
                          ["Bond"], "2026-10-02T03:00:00+00:00", "押金最多四周租金。"), 1.0)
QUESTION = {
    "id": "t01", "lang": "zh", "topic": "tenancy", "type": "simple",
    "question": "押金最多多少？", "gold_urls": ["https://www.tenancy.govt.nz/bond/"],
    "key_points": ["押金最多为 4 周租金"],
}


def judge(score: int, reason: str = "") -> str:
    return json.dumps({"score": score, "reason": reason}, ensure_ascii=False)


def test_answer_body_drops_appended_text():
    """来源列表和免责声明是代码附加的固定文字，交给评判会让忠实度被无关内容影响，必须去掉。"""
    answer = f"押金最多四周租金 [1]。\n\n参考来源：\n[1] Bond - https://x\n\n{DISCLAIMER}"
    assert answer_body(answer) == "押金最多四周租金 [1]。"


def test_correctness_judge_sees_key_points_not_sources():
    """正确率要对照标准要点打分：要点必须出现在评判输入里，否则模型只能凭印象给分。"""
    llm = FakeChatModel([judge(4, "漏了交存期限")])
    out = judge_correctness(llm, "押金最多多少？", "四周租金。\n\n参考来源：\n[1] x",
                            ["押金最多为 4 周租金"])
    assert out.score == 4
    prompt = llm.calls[0][1].content
    assert "- 押金最多为 4 周租金" in prompt
    assert "参考来源" not in prompt


def test_unparsable_judge_excluded_from_average():
    """评判输出两次都无法解析时记为 None 且不计入平均分；当成 0 分会冤枉被评测的系统。"""
    llm = FakeChatModel(["好", "还是不是 JSON", judge(5)])  # 忠实度两次失败，正确率 5 分
    row = evaluate(QUESTION, lambda: run_naive(QUESTION, FakeSearcher(default=[BOND]),
                                               FakeChatModel(["四周租金 [1]。"]), 6), llm)
    assert row["faithfulness"] is None
    assert row["correctness"] == 5
    other = {**row, "faithfulness": 3, "correctness": 3}
    summary = summarize_answers([row, other])
    assert summary["faithfulness"] == 3 and summary["faithfulness_n"] == 1
    assert summary["correctness"] == 4 and summary["correctness_n"] == 2


def test_naive_retrieval_metrics_use_prompt_context():
    """检索指标按放进提示词的父块计算，和回答实际依据的资料一致，两种模式才可比。"""
    searcher = FakeSearcher(default=[BOND])
    row = evaluate(QUESTION, lambda: run_naive(QUESTION, searcher, FakeChatModel(["答 [1]。"]), 6),
                   FakeChatModel([judge(5), judge(5)]))
    assert searcher.calls == [("押金最多多少？", 6, None)]  # 朴素基线不按主题过滤
    assert row["retrieved_urls"] == [BOND.parent.url]
    assert row["rr"] == pytest.approx(1.0)  # 末尾斜杠不同也算命中


def test_agent_clarification_answered_with_preset_reply():
    """缺少关键信息的题 Agent 会反问；评测要用预设回答继续，评的是反问之后的最终回答，
    同时记下发生过反问，否则无法统计反问是否在该反问的题上触发。"""
    question = {**QUESTION, "type": "underspecified", "clarify_reply": "我是正式租客"}
    rewrite_ask = json.dumps({"sub_questions": [{"question": "押金", "query": "bond",
                                                  "topic": "tenancy"}],
                              "clarification": "您是正式租客还是寄宿？"}, ensure_ascii=False)
    rewrite_ok = json.dumps({"sub_questions": [{"question": "押金", "query": "bond",
                                                "topic": "tenancy"}]}, ensure_ascii=False)
    llm = FakeChatModel([rewrite_ask, rewrite_ok, json.dumps({"sufficient": True}), "四周 [1]。"])
    graph = build_graph(llm, FakeSearcher(default=[BOND]), InMemorySaver())

    out = run_agent(question, graph, "eval-t08")

    assert out["clarification"] == "您是正式租客还是寄宿？"
    assert "补充信息：我是正式租客" in llm.calls[1][1].content
    assert out["answer"].startswith("四周 [1]。")
    assert [r.parent.url for r in out["results"]] == [BOND.parent.url]
