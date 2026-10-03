"""父子分块：父块按 Markdown 标题切分，作为回答的上下文；子块在父块内按长度切分，用于检索。"""

import re
from dataclasses import dataclass

from app.ingest.clean import slugify

PARENT_MAX_CHARS = 2000
PARENT_MIN_CHARS = 200
CHILD_CHARS = 500
CHILD_OVERLAP = 80

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
# 句子边界：句末标点后跟空白，或者换行
SENTENCE_END_RE = re.compile(r"[.!?。！？；;](?=\s)|\n")


@dataclass
class Chunk:
    """父块和子块共用的结构；父块的 id 与 parent_id 相同。"""

    id: str
    parent_id: str
    url: str
    title: str
    topic: str
    heading_path: list[str]
    retrieved_at: str
    text: str


@dataclass
class _Block:
    heading_path: list[str]
    text: str


def split_sections(markdown: str) -> list[_Block]:
    """按 #、##、### 标题切分；每段保留自己的标题行，并记录从一级标题开始的标题路径。"""
    blocks: list[_Block] = []
    path: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            blocks.append(_Block([title for _, title in path], text))

    for line in markdown.splitlines():
        m = HEADING_RE.match(line)
        if m:
            flush()
            lines = []
            level = len(m.group(1))
            path = [(lv, t) for lv, t in path if lv < level] + [(level, m.group(2))]
        lines.append(line)
    flush()
    return blocks


def _split_sentences(text: str, max_chars: int) -> list[str]:
    """单个段落过长时，在句子边界处切开；找不到边界才硬切。"""
    pieces = []
    while len(text) > max_chars:
        cut = _last_boundary(text, max_chars // 2, max_chars) or max_chars
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


def split_long(block: _Block, max_chars: int = PARENT_MAX_CHARS) -> list[_Block]:
    """超过上限的块按段落贪心打包，每包不超过上限。"""
    if len(block.text) <= max_chars:
        return [block]
    paragraphs = []
    for para in re.split(r"\n\s*\n", block.text):
        paragraphs.extend(_split_sentences(para.strip(), max_chars))
    out: list[_Block] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + 2 + len(para) > max_chars:
            out.append(_Block(block.heading_path, current))
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(_Block(block.heading_path, current))
    return out


def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    out = []
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        out.append(x)
    return out


def merge_short(blocks: list[_Block], min_chars: int = PARENT_MIN_CHARS) -> list[_Block]:
    """过短的块并入下一个块（最后一块并入前一块）；合并后的标题路径取两者的公共前缀。"""
    merged: list[_Block] = []
    for block in blocks:
        if merged and len(merged[-1].text) < min_chars:
            prev = merged[-1]
            merged[-1] = _Block(
                _common_prefix(prev.heading_path, block.heading_path),
                f"{prev.text}\n\n{block.text}",
            )
        else:
            merged.append(block)
    if len(merged) > 1 and len(merged[-1].text) < min_chars:
        last = merged.pop()
        prev = merged[-1]
        merged[-1] = _Block(
            _common_prefix(prev.heading_path, last.heading_path), f"{prev.text}\n\n{last.text}"
        )
    return merged


def _last_boundary(text: str, lo: int, hi: int) -> int | None:
    """返回 text[lo:hi] 中最后一个句子边界之后的位置。"""
    best = None
    for m in SENTENCE_END_RE.finditer(text, lo, hi):
        best = m.end()
    return best


def split_children(
    text: str, size: int = CHILD_CHARS, overlap: int = CHILD_OVERLAP
) -> list[str]:
    """按约 size 字符切分，相邻子块重叠约 overlap 字符；优先在句子边界断开。"""
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while True:
        end = min(start + size, len(text))
        if end < len(text):
            # 只在后半段找边界，避免子块过短
            end = _last_boundary(text, start + size // 2, end) or end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        # 重叠部分从单词边界开始，避免子块以半个单词开头
        next_start = end - overlap
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return [c for c in chunks if c]


def chunk_document(doc: dict) -> tuple[list[Chunk], list[Chunk]]:
    """把一篇清洗后的文档切成父块和子块，返回 (parents, children)。"""
    blocks: list[_Block] = []
    for section in split_sections(doc["markdown"]):
        blocks.extend(split_long(section))
    blocks = merge_short(blocks)

    base = {
        "url": doc["url"],
        "title": doc["title"],
        "topic": doc["topic"],
        "retrieved_at": doc["retrieved_at"],
    }
    slug = slugify(doc["url"])
    parents, children = [], []
    for i, block in enumerate(blocks):
        parent_id = f"{slug}::{i}"
        parents.append(Chunk(parent_id, parent_id, heading_path=block.heading_path,
                             text=block.text, **base))
        for j, text in enumerate(split_children(block.text)):
            children.append(Chunk(f"{parent_id}::{j}", parent_id,
                                  heading_path=block.heading_path, text=text, **base))
    return parents, children
