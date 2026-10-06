"""混合检索：dense 和 sparse 各取候选子块，用 RRF 融合，按父块去重后回取父块作为上下文。"""

import threading
from dataclasses import dataclass

from app.ingest.chunk import Chunk
from app.retrieval.embeddings import DenseEmbedder, SparseEmbedder
from app.retrieval.store import DENSE, SPARSE, ParentStore, VectorStore

PREFETCH_LIMIT = 20
RRF_K = 60


@dataclass
class SearchResult:
    parent: Chunk
    score: float


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """倒数排名融合：每路排名第 r 位（从 1 开始）贡献 1/(k+r)，按总分降序；同分按首次出现的顺序。

    只用排名不用原始分数，因为余弦相似度和 BM25 分数的量纲不同，不能直接相加。
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def dedupe_parents(
    fused: list[tuple[str, float]], parent_of: dict[str, str]
) -> list[tuple[str, float]]:
    """子块按 parent_id 去重，保留每个父块排名最高的子块的分数和位置。"""
    seen: set[str] = set()
    out = []
    for child_id, score in fused:
        parent_id = parent_of[child_id]
        if parent_id not in seen:
            seen.add(parent_id)
            out.append((parent_id, score))
    return out


class HybridSearcher:
    def __init__(
        self,
        vector_store: VectorStore,
        parent_store: ParentStore,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        prefetch_limit: int = PREFETCH_LIMIT,
    ):
        self.vector_store = vector_store
        self.parent_store = parent_store
        self.dense = dense
        self.sparse = sparse
        self.prefetch_limit = prefetch_limit
        # Qdrant 本地模式和 SQLite 连接都不保证线程安全，并行检索时串行访问；
        # 耗时的向量化（调用 Ollama）在锁外进行，仍然可以并行。
        # 服务运行中更新索引时也持有这把锁，检索会等更新完成
        self.storage_lock = threading.Lock()

    def search(self, query: str, top_k: int = 6, topic: str | None = None) -> list[SearchResult]:
        """返回最多 top_k 个互不相同的父块，按融合分数降序。可以在多个线程中同时调用。"""
        dense_vec = self.dense.embed_query(query)
        sparse_vec = self.sparse.embed_query(query)
        with self.storage_lock:
            dense_hits = self.vector_store.search(dense_vec, DENSE, self.prefetch_limit, topic)
            sparse_hits = self.vector_store.search(sparse_vec, SPARSE, self.prefetch_limit, topic)
        parent_of = {h["id"]: h["parent_id"] for h in dense_hits + sparse_hits}
        fused = rrf_fuse([[h["id"] for h in dense_hits], [h["id"] for h in sparse_hits]])
        ranked = dedupe_parents(fused, parent_of)[:top_k]
        with self.storage_lock:
            parents = {
                p.id: p for p in self.parent_store.get_parents([pid for pid, _ in ranked])
            }
        return [SearchResult(parents[pid], score) for pid, score in ranked if pid in parents]
