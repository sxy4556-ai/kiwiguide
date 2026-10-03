"""把 data/processed 中的文档分块并写入 Qdrant 和父块库；只重建内容有变化的页面。

用法：uv run python scripts/build_index.py
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.ingest.index import build_index, load_processed  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.retrieval.embeddings import (  # noqa: E402
    make_dense_embedder,
    make_sparse_embedder,
    probe_dimension,
)
from app.retrieval.store import ParentStore, VectorStore  # noqa: E402


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    docs = load_processed(settings.data_dir)
    if not docs:
        print("data/processed 中没有文档，请先运行 scripts/fetch_sources.py")
        return 1

    start = time.perf_counter()
    dense = make_dense_embedder(settings)
    sparse = make_sparse_embedder(settings)
    dim = probe_dimension(dense)
    print(f"向量模型 {settings.embed_model}，维度 {dim}；稀疏模型 {settings.sparse_model}")

    vector_store = VectorStore.open(settings.data_dir / "qdrant", dim)
    parent_store = ParentStore(settings.data_dir / "parents.sqlite")
    try:
        stats = build_index(docs, vector_store, parent_store, dense, sparse)
        n_docs, n_parents = parent_store.count()
        n_children = vector_store.count()
    finally:
        vector_store.close()
        parent_store.close()

    elapsed = time.perf_counter() - start
    print(
        f"\n本次：新增 {stats.added}，更新 {stats.updated}，未变化 {stats.unchanged}，"
        f"删除 {stats.removed} 个页面；写入父块 {stats.parents}、子块 {stats.children}"
    )
    print(f"索引现有：页面 {n_docs}，父块 {n_parents}，子块 {n_children}")
    print(f"耗时：{elapsed:.1f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
