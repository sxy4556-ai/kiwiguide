"""按 sources.yaml 抓取并清洗官方页面，输出到 data/processed/<topic>/<slug>.json。

用法：uv run python scripts/fetch_sources.py [--sources sources.yaml]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.ingest.clean import build_document, save_document  # noqa: E402
from app.ingest.fetch import Fetcher  # noqa: E402
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
    ok, skipped, failed = 0, [], []
    try:
        for i, src in enumerate(sources, 1):
            url = src["url"]
            result = fetcher.fetch(url)
            if result.skipped:
                skipped.append((url, result.error))
                print(f"[{i}/{len(sources)}] 跳过 {url}：{result.error}")
                continue
            if not result.ok:
                failed.append((url, result.error))
                print(f"[{i}/{len(sources)}] 失败 {url}：{result.error}")
                continue
            doc = build_document(url, src["topic"], result.html, title=src.get("title"))
            if not doc["markdown"]:
                failed.append((url, "未提取到正文"))
                print(f"[{i}/{len(sources)}] 失败 {url}：未提取到正文")
                continue
            path = save_document(doc, settings.data_dir)
            ok += 1
            print(f"[{i}/{len(sources)}] 成功 {url} -> {path}（{len(doc['markdown'])} 字符）")
    finally:
        fetcher.close()

    total = len(sources)
    print(f"\n共 {total} 个来源：成功 {ok}，失败 {len(failed)}，跳过 {len(skipped)}")
    if total:
        print(f"成功率：{ok / total:.1%}")
    for url, reason in failed:
        print(f"  失败：{url}（{reason}）")
    for url, reason in skipped:
        print(f"  跳过：{url}（{reason}）")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
