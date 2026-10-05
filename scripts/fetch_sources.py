"""按 sources.yaml 抓取并清洗官方页面，输出到 data/processed/<topic>/<slug>.json。

用法：uv run python scripts/fetch_sources.py [--sources sources.yaml]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.ingest.fetch import Fetcher  # noqa: E402
from app.ingest.refresh import fetch_sources  # noqa: E402
from app.ingest.sources import load_sources  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取官方页面并清洗为 Markdown")
    parser.add_argument("--sources", default="sources.yaml", help="来源清单路径")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    sources = load_sources(args.sources)
    fetcher = Fetcher()
    try:
        summary = fetch_sources(sources, fetcher, settings.data_dir, on_progress=print)
    finally:
        fetcher.close()

    total = summary.total
    print(f"\n共 {total} 个来源：成功 {summary.ok}，失败 {len(summary.failed)}，"
          f"跳过 {len(summary.skipped)}")
    if total:
        print(f"成功率：{summary.ok / total:.1%}")
    for url, reason in summary.failed:
        print(f"  失败：{url}（{reason}）")
    for url, reason in summary.skipped:
        print(f"  跳过：{url}（{reason}）")
    return 0 if not summary.failed else 1


if __name__ == "__main__":
    sys.exit(main())
