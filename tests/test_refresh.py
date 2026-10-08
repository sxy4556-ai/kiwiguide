"""抓取流程测试：用假抓取器返回离线 HTML，不访问网络。"""

import json
from pathlib import Path

from app.ingest.fetch import FetchResult
from app.ingest.index import IndexStats
from app.ingest.refresh import FetchSummary, describe_refresh, fetch_sources

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


def test_describe_refresh_reports_every_count():
    """更新摘要必须同时给出抓取结果和索引变化的每一项数字：维护者靠它判断官网是否改版、
    哪些页面没能更新；漏掉失败或删除的数量，会让过期内容悄悄留在索引里。"""
    fetched = FetchSummary(total=5, ok=3, failed=[("u1", "HTTP 500")], skipped=[("u2", "robots")])
    stats = IndexStats(added=1, updated=2, unchanged=4, removed=1)
    text = describe_refresh(fetched, stats)
    assert text == ("抓取 5 个来源：成功 3，失败 1，跳过 1；"
                    "索引：新增 1，更新 2，未变化 4，删除 1 个页面")
