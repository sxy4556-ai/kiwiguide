"""抓取流程测试：用假抓取器返回离线 HTML，不访问网络。"""

import json
from pathlib import Path

from app.ingest.fetch import FetchResult
from app.ingest.refresh import fetch_sources

FIXTURE = Path(__file__).parent / "fixtures" / "bond_page.html"


class FakeFetcher:
    def __init__(self, results: dict[str, FetchResult]):
        self.results = results

    def fetch(self, url: str) -> FetchResult:
        return self.results[url]


def test_fetch_sources_counts_and_saves(tmp_path):
    """成功、失败、跳过必须分别统计并记录原因：/ingest/refresh 和抓取脚本都靠这份摘要
    告诉用户哪些页面没更新；只有成功的页面才能写进 data/processed，失败的不能留下空文件。"""
    html = FIXTURE.read_text(encoding="utf-8")
    sources = [
        {"url": "https://x.govt.nz/bond", "topic": "tenancy"},
        {"url": "https://x.govt.nz/gone", "topic": "tenancy"},
        {"url": "https://x.govt.nz/private", "topic": "tax"},
        {"url": "https://x.govt.nz/empty", "topic": "visa"},
    ]
    fetcher = FakeFetcher({
        "https://x.govt.nz/bond": FetchResult("https://x.govt.nz/bond", ok=True, html=html),
        "https://x.govt.nz/gone": FetchResult("https://x.govt.nz/gone", ok=False,
                                              error="HTTP 404"),
        "https://x.govt.nz/private": FetchResult("https://x.govt.nz/private", ok=False,
                                                 skipped=True, error="robots.txt 禁止抓取"),
        "https://x.govt.nz/empty": FetchResult("https://x.govt.nz/empty", ok=True,
                                               html="<html><body></body></html>"),
    })
    lines: list[str] = []
    summary = fetch_sources(sources, fetcher, tmp_path, on_progress=lines.append)

    assert (summary.total, summary.ok) == (4, 1)
    assert summary.failed == [("https://x.govt.nz/gone", "HTTP 404"),
                              ("https://x.govt.nz/empty", "未提取到正文")]
    assert summary.skipped == [("https://x.govt.nz/private", "robots.txt 禁止抓取")]
    saved = list((tmp_path / "processed").glob("*/*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding="utf-8"))["url"] == "https://x.govt.nz/bond"
    assert len(lines) == 4 and lines[0].startswith("[1/4] 成功")
