"""正文清洗测试：使用 tests/fixtures 中的离线 HTML，不访问网络。"""

import json
from pathlib import Path

from app.ingest.clean import build_document, content_hash, save_document, slugify

FIXTURE = Path(__file__).parent / "fixtures" / "bond_page.html"
URL = "https://www.tenancy.govt.nz/starting-a-tenancy/bond/"


def _markdown() -> str:
    return build_document(URL, "tenancy", FIXTURE.read_text(encoding="utf-8"))["markdown"]


def test_heading_levels_preserved():
    """标题层级必须保留：Day 2 的父块按 #、##、### 切分，层级丢了就无法按章节分块。"""
    lines = _markdown().splitlines()
    assert "# Bond" in lines
    assert "## How much bond can a landlord ask for" in lines
    assert "### Lodging the bond" in lines


def test_navigation_and_footer_removed():
    """导航和页脚必须去掉：这些噪音进入索引后会在每个查询里被误命中，挤掉真正的正文。"""
    md = _markdown()
    assert "Ending a tenancy" not in md
    assert "Privacy policy" not in md
    assert "0800 836 262" not in md


def test_body_text_kept():
    """正文里的关键事实（如押金上限）必须完整保留，否则回答会缺少依据。"""
    assert "up to four weeks' rent" in _markdown()


def test_document_fields_and_save(tmp_path):
    """输出文件的路径和字段是后续分块、引用的契约，缺字段会导致回答无法附出处。"""
    doc = build_document(URL, "tenancy", FIXTURE.read_text(encoding="utf-8"))
    path = save_document(doc, tmp_path)
    assert path == tmp_path / "processed" / "tenancy" / f"{slugify(URL)}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved) == {"url", "title", "topic", "retrieved_at", "content_hash", "markdown"}
    assert saved["title"] == "Bond"


def test_manual_title_overrides_page_title():
    """sources.yaml 中手工填写的标题优先，用来修正页面标题不清楚的情况。"""
    doc = build_document(URL, "tenancy", FIXTURE.read_text(encoding="utf-8"), title="押金")
    assert doc["title"] == "押金"


def test_content_hash_stable_and_sensitive():
    """内容哈希必须稳定且对改动敏感：Day 2 的增量索引靠它判断页面是否需要重建。"""
    assert content_hash("# Bond\n内容") == content_hash("# Bond\n内容")
    assert content_hash("# Bond\n内容") != content_hash("# Bond\n内容。")
    assert len(content_hash("x")) == 64


def test_slug_readable_and_safe():
    """文件名要可读且只含安全字符，Windows 和 Linux 上都能直接作为文件名。"""
    assert slugify(URL) == "tenancy-starting-a-tenancy-bond"
    assert slugify("https://www.ird.govt.nz/income-tax/tax-codes?x=1") == "ird-income-tax-tax-codes"


def test_long_slug_truncated_without_collision():
    """超长 URL 截断后仍必须互不相同，否则两个页面会互相覆盖。"""
    base = "https://www.immigration.govt.nz/" + "very-long-segment/" * 10
    a, b = slugify(base + "page-a"), slugify(base + "page-b")
    assert len(a) <= 100 and len(b) <= 100
    assert a != b
