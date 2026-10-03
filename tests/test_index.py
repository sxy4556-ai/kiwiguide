"""存储与增量索引测试：Qdrant 用内存模式，父块库用临时目录，向量模型用假模型。"""

import pytest
from qdrant_client import QdrantClient

from app.ingest.clean import content_hash, save_document
from app.ingest.index import build_index, load_processed
from app.retrieval.store import ParentStore, VectorStore
from tests.fakes import FAKE_DIM, FakeDenseEmbedder, FakeSparseEmbedder

BODY = "Your landlord must lodge the bond with Tenancy Services within 23 working days. " * 6


def make_doc(url: str, markdown: str, topic: str = "tenancy") -> dict:
    return {
        "url": url,
        "title": url.rsplit("/", 1)[-1],
        "topic": topic,
        "retrieved_at": "2026-10-02T03:00:00+00:00",
        "content_hash": content_hash(markdown),
        "markdown": markdown,
    }


@pytest.fixture
def stores(tmp_path):
    vector_store = VectorStore(QdrantClient(":memory:"), FAKE_DIM)
    parent_store = ParentStore(tmp_path / "parents.sqlite")
    yield vector_store, parent_store
    parent_store.close()


def run(docs, stores, dense=None):
    return build_index(docs, *stores, dense or FakeDenseEmbedder(), FakeSparseEmbedder())


def test_parents_fetched_in_requested_order(stores):
    """父块必须按请求的顺序返回：顺序代表检索排名，打乱了引用编号就和相关度对不上。"""
    doc = make_doc("https://x.govt.nz/bond", f"# Bond\n{BODY}\n## Refund\n{BODY}")
    run([doc], stores)
    _, parent_store = stores
    ids = ["x-bond::1", "x-bond::0", "missing::9"]
    assert [p.id for p in parent_store.get_parents(ids)] == ["x-bond::1", "x-bond::0"]
    assert parent_store.get_parents(["x-bond::1"])[0].heading_path == ["Bond", "Refund"]


def test_unchanged_document_skipped(stores):
    """content_hash 不变的页面必须跳过：重新向量化 50 个页面要几分钟，每次全量重建不可接受。"""
    doc = make_doc("https://x.govt.nz/bond", f"# Bond\n{BODY}")
    run([doc], stores)
    dense = FakeDenseEmbedder()
    stats = run([doc], stores, dense)
    assert stats.unchanged == 1 and stats.added == 0 and stats.updated == 0
    assert dense.document_calls == []


def test_changed_document_replaced_not_duplicated(stores):
    """页面内容变化时必须先删旧块再写新块：旧块残留会让过时的规定继续被检索到。"""
    url = "https://x.govt.nz/bond"
    run([make_doc(url, f"# Bond\n{BODY}\n## Old rule\n{BODY}\n## Another\n{BODY}")], stores)
    vector_store, parent_store = stores
    before = vector_store.count()
    stats = run([make_doc(url, f"# Bond\n{BODY}")], stores)
    assert stats.updated == 1
    assert 0 < vector_store.count() < before
    assert parent_store.count() == (1, 1)
    assert parent_store.document_hashes()[url] == content_hash(f"# Bond\n{BODY}")


def test_removed_document_cleaned_up(stores):
    """来源清单里删掉的页面，索引里的旧块也必须删除，否则会引用已不存在的官方页面。"""
    keep = make_doc("https://x.govt.nz/keep", f"# Keep\n{BODY}")
    gone = make_doc("https://x.govt.nz/gone", f"# Gone\n{BODY}")
    run([keep, gone], stores)
    stats = run([keep], stores)
    vector_store, parent_store = stores
    assert stats.removed == 1
    assert set(parent_store.document_hashes()) == {"https://x.govt.nz/keep"}
    hits = vector_store.search(FakeDenseEmbedder().embed_query("Gone"), "dense", 50)
    assert {h["url"] for h in hits} == {"https://x.govt.nz/keep"}


def test_dimension_mismatch_rejected():
    """换了维度不同的向量模型时必须报错：混用两种维度的向量会让检索结果毫无意义。"""
    client = QdrantClient(":memory:")
    VectorStore(client, FAKE_DIM)
    with pytest.raises(ValueError, match="重建索引"):
        VectorStore(client, FAKE_DIM * 2)


def test_load_processed_reads_saved_documents(tmp_path):
    """建索引读取的必须正是 Day 1 抓取脚本保存的文件，两边的路径约定要一致。"""
    doc = make_doc("https://www.tenancy.govt.nz/bond", f"# Bond\n{BODY}")
    save_document(doc, tmp_path)
    assert load_processed(tmp_path) == [doc]
