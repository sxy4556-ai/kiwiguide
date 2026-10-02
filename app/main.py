"""FastAPI 应用入口。"""

import logging

import httpx
from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def check_ollama(base_url: str, timeout: float = 2.0) -> bool:
    """检查 Ollama 服务是否可达；任何异常都视为不可达，不向外抛出。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("Ollama 不可达：%s", exc)
        return False


def create_app() -> FastAPI:
    """应用工厂：创建并配置 FastAPI 实例。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="KiwiGuide", version=__version__, description="新西兰留学生生活助手")

    @app.get("/health", summary="服务健康检查")
    async def health() -> dict:
        ollama_ok = await check_ollama(get_settings().ollama_base_url)
        return {
            "status": "ok" if ollama_ok else "degraded",
            "version": __version__,
            "ollama": ollama_ok,
        }

    return app


app = create_app()
