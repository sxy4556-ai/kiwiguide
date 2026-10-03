"""建索引：按 content_hash 增量更新，只重建内容变化的页面，并清理已不存在页面的旧块。"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.ingest.chunk import Chunk, chunk_document
from app.retrieval.embeddings import DenseEmbedder, SparseEmbedder
from app.retrieval.store import ParentStore, VectorStore

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


@dataclass
class IndexStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    parents: int = 0
    children: int = 0


def load_processed(data_dir: Path) -> list[dict]:
    """读取 `<data_dir>/processed/<topic>/*.json`，按路径排序保证每次顺序一致。"""
    paths = sorted((Path(data_dir) / "processed").glob("*/*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def embedding_text(chunk: Chunk) -> str:
    """向量化时在子块前加上页面标题和标题路径，让只含细节的子块也带上所属主题的语境。"""
    header = " > ".join([chunk.title, *chunk.heading_path])
    return f"{header}\n{chunk.text}"


def _index_children(
    children: list[Chunk], store: VectorStore, dense: DenseEmbedder, sparse: SparseEmbedder
) -> None:
    for i in range(0, len(children), EMBED_BATCH):
        batch = children[i : i + EMBED_BATCH]
        texts = [embedding_text(c) for c in batch]
        store.upsert(batch, dense.embed_documents(texts), sparse.embed_documents(texts))


def build_index(
    docs: list[dict],
    vector_store: VectorStore,
    parent_store: ParentStore,
    dense: DenseEmbedder,
    sparse: SparseEmbedder,
) -> IndexStats:
    stats = IndexStats()
    indexed = parent_store.document_hashes()
    current = {d["url"] for d in docs}

    for url in sorted(set(indexed) - current):
        vector_store.delete_url(url)
        parent_store.delete_url(url)
        stats.removed += 1
        logger.info("删除已不存在的页面：%s", url)

    for doc in docs:
        url = doc["url"]
        if indexed.get(url) == doc["content_hash"]:
            stats.unchanged += 1
            continue
        if url in indexed:
            stats.updated += 1
        else:
            stats.added += 1
        # 新页面也先清理一次：上次运行如果在写向量途中失败，可能留下残缺的子块
        vector_store.delete_url(url)
        parents, children = chunk_document(doc)
        _index_children(children, vector_store, dense, sparse)
        # 向量写完后才记录 content_hash：中途失败时，下次运行会重建这个页面
        parent_store.save_document(doc, parents, len(children))
        stats.parents += len(parents)
        stats.children += len(children)
        logger.info("已索引 %s：父块 %d，子块 %d", url, len(parents), len(children))
    return stats
