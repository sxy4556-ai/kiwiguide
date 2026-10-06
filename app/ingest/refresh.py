"""按来源清单抓取并清洗页面，命令行脚本和 `/ingest/refresh` 共用。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.ingest.clean import build_document, save_document
from app.ingest.fetch import Fetcher


@dataclass
class FetchSummary:
    total: int = 0
    ok: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (url, 原因)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def fetch_sources(
    sources: list[dict],
    fetcher: Fetcher,
    data_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> FetchSummary:
    """逐个抓取、清洗并保存到 `data/processed`；on_progress 收到每个来源的中文进度行。"""
    summary = FetchSummary(total=len(sources))
    report = on_progress or (lambda _line: None)
    for i, src in enumerate(sources, 1):
        url = src["url"]
        prefix = f"[{i}/{len(sources)}]"
        result = fetcher.fetch(url)
        if result.skipped:
            summary.skipped.append((url, result.error))
            report(f"{prefix} 跳过 {url}：{result.error}")
            continue
        if not result.ok:
            summary.failed.append((url, result.error))
            report(f"{prefix} 失败 {url}：{result.error}")
            continue
        doc = build_document(url, src["topic"], result.html, title=src.get("title"))
        if not doc["markdown"]:
            summary.failed.append((url, "未提取到正文"))
            report(f"{prefix} 失败 {url}：未提取到正文")
            continue
        path = save_document(doc, data_dir)
        summary.ok += 1
        report(f"{prefix} 成功 {url} -> {path}（{len(doc['markdown'])} 字符）")
    return summary
