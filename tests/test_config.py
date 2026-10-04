"""配置测试：默认值与环境变量覆盖。"""

from pathlib import Path

from app.config import Settings, get_settings


def test_defaults_match_env_example(monkeypatch):
    """默认值必须与 .env.example 一致，否则没有 .env 的新环境会连到错误的模型或目录。"""
    for name in ["OLLAMA_BASE_URL", "LLM_MODEL", "FALLBACK_LLM_MODEL", "EMBED_MODEL",
                 "SPARSE_MODEL", "DATA_DIR"]:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.llm_model == "gpt-oss:120b-cloud"
    assert settings.fallback_llm_model == "qwen3:4b-instruct-2507-q4_K_M"
    assert settings.embed_model == "qwen3-embedding:0.6b"
    assert settings.sparse_model == "Qdrant/bm25"
    assert settings.data_dir == Path("data")


def test_env_overrides_defaults(monkeypatch):
    """环境变量必须能覆盖默认值：云模型限流时要靠它切换到本地模型。"""
    monkeypatch.setenv("LLM_MODEL", "qwen3:4b")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.llm_model == "qwen3:4b"
    assert settings.log_level == "DEBUG"


def test_get_settings_is_cached():
    """配置对象必须在进程内共享，避免每次请求都重新读取 .env。"""
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_env_example_lists_every_field():
    """.env.example 是配置的说明文档，必须覆盖 Settings 的全部字段。"""
    text = Path(".env.example").read_text(encoding="utf-8")
    for field in Settings.model_fields:
        assert f"{field.upper()}=" in text
