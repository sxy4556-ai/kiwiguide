"""来源清单 `sources.yaml` 的读取与校验。"""

from pathlib import Path

import yaml

TOPICS = {"tenancy", "employment", "visa", "tax"}


def load_sources(path: Path | str = "sources.yaml") -> list[dict]:
    """读取来源清单；主题不合法或 URL 重复时直接报错，避免带着脏数据进入索引。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    seen: set[str] = set()
    for item in sources:
        url, topic = item.get("url"), item.get("topic")
        if not url or topic not in TOPICS:
            raise ValueError(f"来源条目不合法：{item}")
        if url in seen:
            raise ValueError(f"来源 URL 重复：{url}")
        seen.add(url)
    return sources
