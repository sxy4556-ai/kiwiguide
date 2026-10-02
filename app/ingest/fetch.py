"""网页抓取：遵守 robots.txt，同一域名限速，失败自动重试。"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "KiwiGuideBot/0.1 (+https://github.com/sxy4556-ai/kiwiguide)"
MIN_DELAY = 1.0  # 同一域名两次请求的最小间隔（秒）
MAX_RETRIES = 2  # 首次失败后最多再试的次数


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None = None
    html: str = ""
    final_url: str = ""
    error: str = ""
    skipped: bool = False  # 被 robots.txt 禁止时为 True


def parse_robots(text: str) -> RobotFileParser:
    """把 robots.txt 文本解析成解析器对象。"""
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser


def is_allowed(parser: RobotFileParser, url: str, user_agent: str = USER_AGENT) -> bool:
    """判断 robots.txt 是否允许抓取该 URL。"""
    return parser.can_fetch(user_agent, url)


def crawl_delay(parser: RobotFileParser, user_agent: str = USER_AGENT) -> float:
    """取 robots.txt 的 Crawl-delay 与项目最小间隔中较大的一个。"""
    delay = parser.crawl_delay(user_agent)
    return max(MIN_DELAY, float(delay or 0))


class Fetcher:
    """带 robots 缓存和按域名限速的抓取器。"""

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
        )
        self.sleep = sleep
        self.clock = clock
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def _wait(self, host: str, delay: float) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[host] = self.clock()

    def _get(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        self._wait(host, crawl_delay(self._robots_for(url)))
        return self.client.get(url)

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            robots_url = f"{parts.scheme}://{host}/robots.txt"
            self._last_request[host] = self.clock()
            try:
                resp = self.client.get(robots_url)
                if resp.status_code >= 500:
                    # 服务器错误时无法确认规则，保守起见视为全部禁止
                    parser = parse_robots("User-agent: *\nDisallow: /")
                else:
                    # 404 等客户端错误表示没有 robots.txt，按惯例视为全部允许
                    parser = parse_robots(resp.text if resp.status_code == 200 else "")
            except httpx.HTTPError as exc:
                logger.warning("无法获取 %s：%s，视为禁止抓取", robots_url, exc)
                parser = parse_robots("User-agent: *\nDisallow: /")
            self._robots[host] = parser
        return self._robots[host]

    def fetch(self, url: str) -> FetchResult:
        """抓取单个页面；网络错误、5xx 和 429 会重试，其余 4xx 直接判定失败。"""
        if not is_allowed(self._robots_for(url), url):
            logger.info("robots.txt 禁止抓取，跳过：%s", url)
            return FetchResult(url=url, ok=False, skipped=True, error="robots.txt 禁止抓取")

        error = ""
        status = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._get(url)
            except httpx.HTTPError as exc:
                error = f"网络错误：{exc!r}"
            else:
                status = resp.status_code
                if status == 200:
                    return FetchResult(
                        url=url, ok=True, status=status, html=resp.text, final_url=str(resp.url)
                    )
                error = f"HTTP {status}"
                if 400 <= status < 500 and status != 429:
                    break
            logger.warning("抓取失败（第 %d 次）：%s，%s", attempt + 1, url, error)
        return FetchResult(url=url, ok=False, status=status, error=error)

    def close(self) -> None:
        self.client.close()
