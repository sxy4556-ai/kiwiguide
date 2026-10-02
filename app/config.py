"""应用配置：统一从环境变量和 `.env` 读取，字段与 `.env.example` 保持一致。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全部可配置项。环境变量名为字段名的大写形式，例如 `LLM_MODEL`。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "deepseek-v4-flash:cloud"
    fallback_llm_model: str = "qwen3:4b"
    embed_model: str = "qwen3-embedding:0.6b"
    data_dir: Path = Path("data")
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的配置对象；测试中修改环境变量后需调用 `get_settings.cache_clear()`。"""
    return Settings()
