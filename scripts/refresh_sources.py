"""重新抓取所有来源，只为内容有变化的页面重建索引，并打印变化统计。

用法：uv run python scripts/refresh_sources.py [--sources sources.yaml]

Qdrant 本地库同一时间只允许一个进程打开：服务运行时不要运行本脚本，改用 `POST /ingest/refresh`。
抓取失败的页面保留上一次的内容，不会从索引中删除。
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.ingest.fetch import Fetcher  # noqa: E402
from app.ingest.index import build_index, load_processed  # noqa: E402
from app.ingest.refresh import describe_refresh, fetch_sources  # noqa: E402
from app.ingest.sources import load_sources  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.retrieval.embeddings import (  # noqa: E402
    make_dense_embedder,
    make_sparse_embedder,
    probe_dimension,
)
from app.retrieval.store import ParentStore, VectorStore  # noqa: E402


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="重新抓取官方页面并增量更新索引")
    parser.add_argument("--sources", default=str(settings.sources_file), help="来源清单路径")
    args = parser.parse_args()

    setup_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    start = time.perf_counter()
    fetcher = Fetcher()
    try:
        fetched = fetch_sources(load_sources(args.sources), fetcher, settings.data_dir,
                                on_progress=print)
    finally:
        fetcher.close()

    dense = make_dense_embedder(settings)
    sparse = make_sparse_embedder(settings)
    vector_store = VectorStore.open(settings.data_dir / "qdrant", probe_dimension(dense))
    parent_store = ParentStore(settings.data_dir / "parents.sqlite")
    try:
        stats = build_index(load_processed(settings.data_dir), vector_store, parent_store,
                            dense, sparse)
    finally:
        vector_store.close()
        parent_store.close()

    print("\n" + describe_refresh(fetched, stats))
    for url, reason in fetched.failed:
        print(f"  失败：{url}（{reason}）")
    for url, reason in fetched.skipped:
        print(f"  跳过：{url}（{reason}）")
    print(f"耗时：{time.perf_counter() - start:.1f} 秒")
    return 0 if not fetched.failed else 1


if __name__ == "__main__":
    sys.exit(main())
