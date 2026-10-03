"""父子分块测试：纯文本处理，不访问网络。"""

from app.ingest.chunk import (
    CHILD_CHARS,
    PARENT_MAX_CHARS,
    PARENT_MIN_CHARS,
    chunk_document,
    merge_short,
    split_children,
    split_long,
    split_sections,
)

FILLER = "Tenants must pay rent on time and keep the property reasonably clean. " * 4


def _doc(markdown: str) -> dict:
    return {
        "url": "https://www.tenancy.govt.nz/rent-bond-and-bills/bond/",
        "title": "Bond",
        "topic": "tenancy",
        "retrieved_at": "2026-10-02T03:00:00+00:00",
        "markdown": markdown,
    }


def test_sections_split_on_headings_with_path():
    """父块必须按标题切分并记录标题路径：回答引用时要指明出自页面的哪一节，用户才好核对。"""
    md = "# Bond\nintro\n## Paying\npay text\n### Receipt\nreceipt text\n## Refunds\nrefund text"
    blocks = split_sections(md)
    assert [b.heading_path for b in blocks] == [
        ["Bond"],
        ["Bond", "Paying"],
        ["Bond", "Paying", "Receipt"],
        ["Bond", "Refunds"],
    ]
    assert blocks[1].text == "## Paying\npay text"


def test_level_four_heading_does_not_split():
    """只按 #、##、### 切分：四级标题通常是很短的小节，单独成块会产生大量碎片。"""
    blocks = split_sections("## A\ntext\n#### Small\nmore")
    assert len(blocks) == 1


def test_long_section_split_by_paragraph_under_limit():
    """超过 2000 字符的父块必须按段落再切：父块会整体放进提示词，过长会挤占模型上下文。"""
    block = split_sections("## Long\n\n" + "\n\n".join([FILLER] * 12))[0]
    pieces = split_long(block)
    assert len(pieces) > 1
    assert all(len(p.text) <= PARENT_MAX_CHARS for p in pieces)
    assert all(p.heading_path == ["Long"] for p in pieces)


def test_short_blocks_merged_with_neighbour():
    """少于 200 字符的块必须合并：只有一行标题或一句话的父块缺少上下文，检索命中了也答不了题。"""
    md = f"# Bond\nshort intro\n## Paying\n{FILLER}\n## Refunds\n{FILLER}\n## Note\ntiny"
    blocks = merge_short(split_sections(md))
    assert all(len(b.text) >= PARENT_MIN_CHARS for b in blocks)
    # 一级标题的短引言并入下一节，路径取公共前缀
    assert blocks[0].text.startswith("# Bond\nshort intro\n\n## Paying")
    assert blocks[0].heading_path == ["Bond"]
    # 末尾的短块并入前一块，内容不丢
    assert blocks[-1].text.endswith("## Note\ntiny")


def test_children_overlap_and_respect_size():
    """子块要有重叠：一句关键事实如果刚好被切在边界上，重叠能保证它完整出现在某个子块里。"""
    text = " ".join(f"Sentence number {i} explains a tenancy rule." for i in range(60))
    children = split_children(text)
    assert len(children) > 2
    assert all(len(c) <= CHILD_CHARS for c in children)
    for a, b in zip(children, children[1:], strict=False):
        assert b[:30] in a


def test_children_break_at_sentence_boundary():
    """子块优先在句子边界断开：半句话的子块语义不完整，向量检索效果会变差。"""
    text = " ".join(f"Sentence number {i} explains a tenancy rule." for i in range(60))
    for child in split_children(text)[:-1]:
        assert child.endswith(".")


def test_chunk_metadata_complete_and_linked():
    """每个块都必须带完整元数据，子块的 parent_id 必须指向真实父块：出处和父块回取都依赖它们。"""
    parents, children = chunk_document(_doc(f"# Bond\n{FILLER}\n## Refunds\n{FILLER * 3}"))
    parent_ids = {p.id for p in parents}
    assert all(p.parent_id == p.id for p in parents)
    assert {c.parent_id for c in children} == parent_ids
    for chunk in parents + children:
        assert chunk.url.startswith("https://www.tenancy.govt.nz/")
        assert chunk.title == "Bond"
        assert chunk.topic == "tenancy"
        assert chunk.retrieved_at == "2026-10-02T03:00:00+00:00"
        assert chunk.heading_path
    assert len({c.id for c in children}) == len(children)


def test_chunk_ids_stable():
    """同一内容重复分块，id 必须相同：增量索引和评测结果的对比都依赖稳定的 id。"""
    doc = _doc(f"# Bond\n{FILLER}\n## Refunds\n{FILLER}")
    assert [c.id for c in chunk_document(doc)[1]] == [c.id for c in chunk_document(doc)[1]]
