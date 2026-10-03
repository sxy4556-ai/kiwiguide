"""混合检索测试：RRF 融合、父块去重、主题过滤；使用假向量模型和内存 Qdrant。"""

import pytest
from qdrant_client import QdrantClient

from app.ingest.index import build_index
from app.retrieval.search import HybridSearcher, dedupe_parents, rrf_fuse
from app.retrieval.store import ParentStore, VectorStore
from tests.fakes import FAKE_DIM, FakeDenseEmbedder, FakeSparseEmbedder
from tests.test_index import make_doc


def test_rrf_rewards_agreement_between_retrievers():
    """两路都排得靠前的结果必须排在只被一路命中的结果前面，这正是混合检索比单路稳的原因。"""
    fused = rrf_fuse([["a", "b", "c"], ["b", "d", "a"]], k=60)
    ids = [i for i, _ in fused]
    assert ids[:2] == ["b", "a"]  # b: 1/62+1/61，a: 1/61+1/63
    assert set(ids[2:]) == {"c", "d"}
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_ignores_raw_score_scale():
    """RRF 只看排名：单路排第一的贡献固定为 1/(k+1)，不会因为 BM25 分数大就压过稠密检索。"""
    fused = dict(rrf_fuse([["x"], ["y"]], k=60))
    assert fused["x"] == fused["y"] == pytest.approx(1 / 61)


def test_dedupe_keeps_best_child_per_parent():
    """同一父块的多个子块只保留排名最高的一次：否则上下文里会重复塞同一段原文，挤掉其他来源。"""
    fused = [("p1::0", 0.9), ("p1::1", 0.8), ("p2::0", 0.7), ("p1::2", 0.6)]
    parent_of = {"p1::0": "p1", "p1::1": "p1", "p1::2": "p1", "p2::0": "p2"}
    assert dedupe_parents(fused, parent_of) == [("p1", 0.9), ("p2", 0.7)]


@pytest.fixture
def searcher(tmp_path):
    long = " ".join(f"Bond rule {i} says the landlord lodges bond money." for i in range(40))
    docs = [
        make_doc("https://www.tenancy.govt.nz/bond", f"# Bond\n{long}", "tenancy"),
        make_doc(
            "https://www.ird.govt.nz/tax-codes",
            "# Tax codes\n" + "Use the tax code M for your main job and pay tax. " * 8,
            "tax",
        ),
        make_doc(
            "https://www.employment.govt.nz/minimum-wage",
            "# Minimum wage\n" + "The adult minimum wage applies to employees aged 16. " * 8,
            "employment",
        ),
    ]
    vector_store = VectorStore(QdrantClient(":memory:"), FAKE_DIM)
    parent_store = ParentStore(tmp_path / "parents.sqlite")
    dense, sparse = FakeDenseEmbedder(), FakeSparseEmbedder()
    build_index(docs, vector_store, parent_store, dense, sparse)
    yield HybridSearcher(vector_store, parent_store, dense, sparse)
    parent_store.close()


def test_search_returns_distinct_parents_with_relevant_first(searcher):
    """检索结果必须是互不重复的父块，且最相关的页面排第一，这是回答质量的基础。"""
    results = searcher.search("how does the landlord lodge bond money", top_k=6)
    ids = [r.parent.id for r in results]
    assert len(ids) == len(set(ids))
    assert results[0].parent.url == "https://www.tenancy.govt.nz/bond"
    assert results[0].parent.text.startswith("# Bond")


def test_topic_filter_restricts_results(searcher):
    """指定主题后只能返回该主题的内容：Agent 判断出是税务问题时，不应混入租房页面。"""
    results = searcher.search("bond money tax code", top_k=6, topic="tax")
    assert results
    assert {r.parent.topic for r in results} == {"tax"}


def test_top_k_limits_result_count(searcher):
    """top_k 决定放进提示词的父块数量，必须严格遵守，否则上下文长度失控。"""
    assert len(searcher.search("bond", top_k=1)) == 1
