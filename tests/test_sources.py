"""来源清单测试：校验仓库中的 sources.yaml 和加载逻辑。"""

from urllib.parse import urlsplit

import pytest

from app.ingest.sources import TOPICS, load_sources

OFFICIAL_HOSTS = {
    "www.tenancy.govt.nz",
    "www.employment.govt.nz",
    "www.immigration.govt.nz",
    "www.ird.govt.nz",
}


def test_repo_sources_cover_all_topics_from_official_sites():
    """项目只依据政府官网作答：每个来源都必须来自四个官方站点，且四个主题都有覆盖。"""
    sources = load_sources("sources.yaml")
    assert 30 <= len(sources) <= 50
    assert {s["topic"] for s in sources} == TOPICS
    assert all(urlsplit(s["url"]).netloc in OFFICIAL_HOSTS for s in sources)


def test_invalid_topic_rejected(tmp_path):
    """主题写错会让检索时的主题过滤失效，必须在加载时就报错。"""
    path = tmp_path / "sources.yaml"
    path.write_text("sources:\n  - url: https://a.govt.nz/x\n    topic: food\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_sources(path)


def test_duplicate_url_rejected(tmp_path):
    """重复的 URL 会生成重复的块，干扰检索排序，必须拒绝。"""
    path = tmp_path / "sources.yaml"
    entry = "  - url: https://a.govt.nz/x\n    topic: tax\n"
    path.write_text("sources:\n" + entry * 2, encoding="utf-8")
    with pytest.raises(ValueError):
        load_sources(path)
