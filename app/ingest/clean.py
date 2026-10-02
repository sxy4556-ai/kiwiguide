"""正文清洗：用 trafilatura 提取正文并转成 Markdown，生成带元数据的文档。"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import trafilatura

MAX_SLUG_LEN = 100


def slugify(url: str) -> str:
    """由 URL 生成文件名：站点简称加路径，只含小写字母、数字和连字符。"""
    parts = urlsplit(url)
    site = parts.netloc.lower().removeprefix("www.").removesuffix(".govt.nz")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{site}/{parts.path}".lower()).strip("-")
    if len(slug) > MAX_SLUG_LEN:
        # 超长时截断并附上 URL 的短哈希，保证不同 URL 不会撞名
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[: MAX_SLUG_LEN - 9].rstrip('-')}-{digest}"
    return slug


def content_hash(markdown: str) -> str:
    """正文的 sha256，用于判断页面内容是否变化。"""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def html_to_markdown(html: str, url: str = "") -> str:
    """提取正文并转成 Markdown，保留标题层级和表格，去掉导航、页脚等噪音。"""
    markdown = trafilatura.extract(
        html,
        url=url or None,
        output_format="markdown",
        include_formatting=True,
        include_tables=True,
        include_links=False,
        include_images=False,
        include_comments=False,
        favor_precision=True,
    )
    return normalize_whitespace(markdown or "")


def normalize_whitespace(markdown: str) -> str:
    """规整空白：部分页面的列表项内含大量缩进和空行，会浪费分块长度并干扰检索。"""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in markdown.splitlines()]
    text = "\n".join(lines)
    # 只剩列表标记的行与下一行正文合并
    text = re.sub(r"^([-*]|\d+\.)\n+", r"\1 ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_title(html: str) -> str:
    """从页面元数据中取标题，取不到时返回空字符串。"""
    meta = trafilatura.extract_metadata(html)
    return (meta.title if meta and meta.title else "").strip()


def build_document(
    url: str, topic: str, html: str, title: str | None = None, retrieved_at: str | None = None
) -> dict:
    """组装输出文档；sources.yaml 中手工填写的标题优先于页面标题。"""
    markdown = html_to_markdown(html, url)
    return {
        "url": url,
        "title": title or extract_title(html) or url,
        "topic": topic,
        "retrieved_at": retrieved_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "content_hash": content_hash(markdown),
        "markdown": markdown,
    }


def save_document(doc: dict, data_dir: Path) -> Path:
    """保存到 `<data_dir>/processed/<topic>/<slug>.json`。"""
    path = Path(data_dir) / "processed" / doc["topic"] / f"{slugify(doc['url'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
