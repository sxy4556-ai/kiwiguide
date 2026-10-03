"""朴素 RAG 测试：假检索结果和假模型，检查引用编号与来源的对应关系。"""

from app.ingest.chunk import Chunk
from app.rag.naive import DISCLAIMER, answer_question, format_context
from app.retrieval.search import SearchResult
from tests.fakes import FakeChatModel


def _result(n: int, url: str, title: str) -> SearchResult:
    chunk = Chunk(f"p{n}", f"p{n}", url, title, "tenancy", [title, "Rules"],
                  "2026-10-02T03:00:00+00:00", f"正文 {n}")
    return SearchResult(chunk, 1.0 / n)


RESULTS = [
    _result(1, "https://www.tenancy.govt.nz/bond", "Bond"),
    _result(2, "https://www.tenancy.govt.nz/rent", "Increasing rent"),
]


def test_context_numbered_in_retrieval_order():
    """资料编号必须按检索顺序从 [1] 开始：模型引用 [n] 时，用户要能据此找到对应的官方页面。"""
    ctx = format_context(RESULTS)
    assert ctx.index("[1] Bond（Bond > Rules）") < ctx.index("[2] Increasing rent")
    assert "来源：https://www.tenancy.govt.nz/bond" in ctx


def test_answer_sources_match_citation_numbers():
    """回答末尾的参考来源编号必须和正文的 [n] 一一对应，并带链接和抓取日期，方便用户核实。"""
    llm = FakeChatModel(["押金（bond）最多四周租金 [1]，涨租需提前通知 [2]。"])
    result = answer_question("押金和涨租的规定？", lambda q: RESULTS, llm)
    assert [(c.index, c.url) for c in result.citations] == [
        (1, "https://www.tenancy.govt.nz/bond"),
        (2, "https://www.tenancy.govt.nz/rent"),
    ]
    assert "[1] Bond - https://www.tenancy.govt.nz/bond（抓取于 2026-10-02）" in result.answer
    assert "[2] Increasing rent - https://www.tenancy.govt.nz/rent" in result.answer
    assert result.answer.endswith(DISCLAIMER)
    # 提示词里确实带上了编号资料
    assert "[2] Increasing rent" in llm.calls[0][1].content


def test_no_results_does_not_call_model():
    """检索为空时必须直接说明查不到，不调用模型：否则模型会凭记忆回答，给出没有出处的结论。"""
    llm = FakeChatModel([])
    result = answer_question("火星签证怎么办？", lambda q: [], llm)
    assert llm.calls == []
    assert result.citations == []
    assert "没有检索到" in result.answer
