"""对话模型：统一从这里创建，主模型调用失败时自动切换到备用模型。"""

from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama

from app.config import Settings, get_settings


def make_chat_model(model: str, settings: Settings, temperature: float = 0.0) -> ChatOllama:
    return ChatOllama(model=model, base_url=settings.ollama_base_url, temperature=temperature)


def get_chat_model(settings: Settings | None = None, temperature: float = 0.0) -> Runnable:
    """返回 `LLM_MODEL`；它报错时（如云模型限流、断网）改用 `FALLBACK_LLM_MODEL` 重试同一请求。"""
    settings = settings or get_settings()
    primary = make_chat_model(settings.llm_model, settings, temperature)
    if not settings.fallback_llm_model or settings.fallback_llm_model == settings.llm_model:
        return primary
    fallback = make_chat_model(settings.fallback_llm_model, settings, temperature)
    return primary.with_fallbacks([fallback])
