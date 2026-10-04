"""Agent 测试：假模型按顺序给出各节点的输出，假检索器返回编排好的结果，不访问网络。

一轮问答中模型的调用顺序是：rewrite → grade →（重试时再 rewrite → grade）→ generate。
"""

import json

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import ask, build_graph, open_checkpointer
from app.agent.nodes import (
    MAX_RETRIES,
    AgentNodes,
    RewriteOutput,
    parse_json,
    renumber_citations,
)
from app.ingest.chunk import Chunk
from app.rag.naive import DISCLAIMER
from app.retrieval.search import SearchResult
from tests.fakes import FakeChatModel, FakeSearcher


def _result(n: int, url: str, title: str) -> SearchResult:
    chunk = Chunk(f"p{n}", f"p{n}", url, title, "tenancy", [title],
                  "2026-10-02T03:00:00+00:00", f"正文 {n}")
    return SearchResult(chunk, 1.0 / n)


BOND = _result(1, "https://www.tenancy.govt.nz/bond", "Bond")
RENT = _result(2, "https://www.tenancy.govt.nz/rent", "Increasing rent")
NOTICE = _result(3, "https://www.tenancy.govt.nz/notice", "Giving notice")


def rewrite_reply(*queries: str, topic: str | None = "tenancy") -> str:
    return json.dumps({"queries": list(queries), "topic": topic})


def grade_reply(sufficient: bool, reason: str = "") -> str:
    return json.dumps({"sufficient": sufficient, "reason": reason}, ensure_ascii=False)


def test_citations_renumbered_to_match_sources():
    """正文的 [n] 必须和来源列表一一对应：用户靠编号找到官方页面核实，编号错位等于给了错误出处。

    两条检索词的结果交替合并后资料顺序为 BOND、NOTICE、RENT。模型先引用了第 3 份资料，
    所以它要变成 [1]；没被引用的 NOTICE 不应出现在来源列表里。
    """
    llm = FakeChatModel([
        rewrite_reply("bond amount", "rent increase notice"),
        grade_reply(True),
        "押金（bond）最多四周租金 [3]，涨租需提前通知 [3][1]。",
    ])
    searcher = FakeSearcher({"bond amount": [BOND, RENT], "rent increase notice": [NOTICE]})
    state = ask(build_graph(llm, searcher), "押金和涨租有什么规定？", "t1")

    assert state["answer"].startswith("押金（bond）最多四周租金 [1]，涨租需提前通知 [1][2]。")
    assert [(c["index"], c["url"]) for c in state["citations"]] == [
        (1, RENT.parent.url), (2, BOND.parent.url),
    ]
    assert NOTICE.parent.url not in state["answer"]
    assert "[2] Bond - https://www.tenancy.govt.nz/bond（抓取于 2026-10-02）" in state["answer"]
    assert state["answer"].endswith(DISCLAIMER)
    # 英文检索词和主题过滤确实传给了检索器
    assert searcher.calls[0] == ("bond amount", 6, "tenancy")


def test_out_of_range_citation_removed():
    """模型编出资料里不存在的编号时必须删掉，否则用户会看到一个找不到来源的引用。"""
    body, citations = renumber_citations("结论 [5]，另一结论 [1, 2]。", [BOND, RENT])
    assert body == "结论 ，另一结论 [1][2]。"
    assert [c.url for c in citations] == [BOND.parent.url, RENT.parent.url]


def test_insufficient_results_trigger_rewrite_with_reason():
    """资料不足时要带着失败原因重新改写：只重复同样的检索词会拿到同样的结果，纠错就失去意义。"""
    llm = FakeChatModel([
        rewrite_reply("bond"),
        grade_reply(False, "缺少押金退还时限"),
        rewrite_reply("bond refund timeframe"),
        grade_reply(True),
        "押金应在规定时间内退还 [1]。",
    ])
    searcher = FakeSearcher({"bond": [RENT], "bond refund timeframe": [BOND]})
    state = ask(build_graph(llm, searcher), "押金多久退？", "t1")

    second_rewrite_prompt = llm.calls[2][1].content
    assert "缺少押金退还时限" in second_rewrite_prompt
    assert "bond" in second_rewrite_prompt  # 上一次的检索词也要告诉模型
    assert state["retries"] == 1
    assert state["citations"][0]["url"] == BOND.parent.url


def test_retries_capped_at_two():
    """重试最多 2 次：资料库里确实没有答案时，无限重试会让用户一直等不到回复。"""
    replies = []
    for _ in range(MAX_RETRIES + 1):
        replies += [rewrite_reply("something"), grade_reply(False, "无关")]
    llm = FakeChatModel([*replies, "资料里没有提到这一点 [1]。"])
    state = ask(build_graph(llm, FakeSearcher(default=[BOND])), "某个冷门问题", "t1")

    assert state["retries"] == MAX_RETRIES
    assert len(llm.calls) == 2 * (MAX_RETRIES + 1) + 1
    # 最终仍然作答，并在提示词中提醒模型资料可能不足
    assert "资料可能不足" in llm.calls[-1][1].content
    assert llm.replies == []


def test_no_results_answers_without_model():
    """一直检索不到资料时，必须直接说明查不到而不是让模型自由发挥，否则会给出没有出处的结论。"""
    llm = FakeChatModel([rewrite_reply("mars visa")] * (MAX_RETRIES + 1))
    state = ask(build_graph(llm, FakeSearcher()), "火星签证怎么办？", "t1")

    assert len(llm.calls) == MAX_RETRIES + 1  # 只有 rewrite 调用了模型
    assert "没有检索到" in state["answer"]
    assert state["citations"] == []


def test_invalid_json_retried_once_then_degrades():
    """模型输出不是 JSON 时先重试一次，仍失败就用原问题检索。

    小模型偶尔格式出错，不能因此整轮失败。
    """
    llm = FakeChatModel(["好的，我来改写", "还是不是 JSON", grade_reply(True), "回答 [1]。"])
    searcher = FakeSearcher(default=[BOND])
    state = ask(build_graph(llm, searcher), "押金多少？", "t1")

    assert "无法解析" in llm.calls[1][-1].content  # 重试时把错误告诉了模型
    assert searcher.calls == [("押金多少？", 6, None)]  # 降级：原问题、不过滤主题
    assert state["citations"][0]["url"] == BOND.parent.url


def test_parse_json_tolerates_fences_and_think():
    """推理模型会输出 <think> 段，常见模型会用 ```json 包裹：这些都应该能解析，减少无谓的降级。"""
    text = '<think>想一想 {"x": 1}</think>\n```json\n{"queries": ["bond"], "topic": "TAX"}\n```'
    out = parse_json(text, RewriteOutput)
    assert out.queries == ["bond"]
    assert out.topic == "tax"


def test_unknown_topic_disables_filter():
    """主题不在四个之内时不能拿去过滤：用不存在的主题过滤会把所有结果都滤掉。"""
    assert RewriteOutput(queries=["a"], topic="housing").topic is None


def test_multi_turn_context_survives_restart(tmp_path):
    """追问（"那押金呢？"）要靠上一轮的内容才能改写成完整检索词。

    会话存在 SQLite 里，服务重启后也不能丢；不同 thread_id 的会话互不影响。
    """
    path = tmp_path / "checkpoints.sqlite"
    searcher = FakeSearcher(default=[BOND])

    saver = open_checkpointer(path)
    llm1 = FakeChatModel([rewrite_reply("rent increase"), grade_reply(True), "涨租规定 [1]。"])
    ask(build_graph(llm1, searcher, saver), "房东多久能涨一次租？", "student-1")
    saver.conn.close()

    saver = open_checkpointer(path)
    llm2 = FakeChatModel([rewrite_reply("bond rules"), grade_reply(True), "押金规定 [1]。"])
    state = ask(build_graph(llm2, searcher, saver), "那押金呢？", "student-1")
    saver.conn.close()

    rewrite_prompt = llm2.calls[0][1].content
    assert "房东多久能涨一次租？" in rewrite_prompt
    assert "涨租规定" in rewrite_prompt
    assert [m.type for m in state["messages"]] == ["human", "ai", "human", "ai"]
    # 另一个会话互不影响
    llm3 = FakeChatModel([rewrite_reply("bond"), grade_reply(True), "回答 [1]。"])
    saver = open_checkpointer(path)
    other = ask(build_graph(llm3, searcher, saver), "押金多少？", "student-2")
    saver.conn.close()
    assert len(other["messages"]) == 2


def _history(rounds: int) -> list:
    msgs = []
    for i in range(rounds):
        msgs += [HumanMessage(f"问题{i}", id=f"h{i}"), AIMessage(f"回答{i}", id=f"a{i}")]
    return [*msgs, HumanMessage("当前问题", id="now")]


def test_summarize_only_after_six_rounds():
    """超过 6 轮才压缩：太早压缩会丢掉细节，太晚压缩会让上下文过长、拖慢小模型。"""
    llm = FakeChatModel(["用户是学生签证，在问租房。"])
    nodes = AgentNodes(llm, FakeSearcher())

    assert nodes.summarize({"messages": _history(6)}) == {}
    assert llm.calls == []

    out = nodes.summarize({"messages": _history(7)})
    assert out["summary"] == "用户是学生签证，在问租房。"
    removed = {m.id for m in out["messages"]}
    # 保留最近两轮问答和当前问题，其余交给摘要
    assert removed == {f"h{i}" for i in range(5)} | {f"a{i}" for i in range(5)}
    assert "问题0" in llm.calls[0][1].content
