"""抓取测试：用假的 robots 内容和 httpx.MockTransport，不访问网络。"""

import httpx

from app.ingest.fetch import Fetcher, crawl_delay, is_allowed, parse_robots

ROBOTS = """
User-agent: *
Disallow: /admin
Disallow: /search-results
Crawl-delay: 5
"""


def test_robots_disallow_respected():
    """robots.txt 禁止的路径必须跳过：这是使用政府网站数据的前提。"""
    parser = parse_robots(ROBOTS)
    assert not is_allowed(parser, "https://www.employment.govt.nz/admin/login")
    assert not is_allowed(parser, "https://www.employment.govt.nz/search-results?q=pay")
    assert is_allowed(parser, "https://www.employment.govt.nz/pay-and-hours/minimum-wage")


def test_crawl_delay_never_below_one_second():
    """请求间隔至少 1 秒；站点声明了更长的 Crawl-delay 时以站点为准，避免给官网造成压力。"""
    assert crawl_delay(parse_robots(ROBOTS)) == 5.0
    assert crawl_delay(parse_robots("User-agent: *\nDisallow:")) == 1.0


def _fetcher(handler) -> tuple[Fetcher, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher(client=client, sleep=sleeps.append, clock=lambda: 0.0), sleeps


def test_disallowed_url_is_skipped_without_request():
    """被禁止的页面不能发出任何请求，只能标记为跳过。"""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, text=ROBOTS if request.url.path == "/robots.txt" else "ok")

    fetcher, _ = _fetcher(handler)
    result = fetcher.fetch("https://example.govt.nz/admin/page")
    assert result.skipped and not result.ok
    assert requested == ["/robots.txt"]


def test_server_error_retried_twice_then_reported():
    """5xx 要重试 2 次（共 3 次请求），仍失败时必须带上失败原因，方便在日志中排查。"""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        return httpx.Response(503)

    fetcher, sleeps = _fetcher(handler)
    result = fetcher.fetch("https://example.govt.nz/page")
    assert calls == 3
    assert not result.ok and "503" in result.error
    assert sleeps and all(s >= 1.0 for s in sleeps)


def test_not_found_is_not_retried():
    """404 是确定的失败，重试只会浪费请求，必须立即返回。"""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        return httpx.Response(404)

    fetcher, _ = _fetcher(handler)
    result = fetcher.fetch("https://example.govt.nz/missing")
    assert calls == 1 and result.status == 404
