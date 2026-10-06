"""FastAPI 应用入口。"""

import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.routes import router
from app.api.service import ChatService, ServiceError, build_service
from app.config import get_settings
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

INDEX_HTML = Path(__file__).parent / "web" / "index.html"
HTTP_MESSAGES = {404: "接口不存在", 405: "不支持这个请求方法"}


async def check_ollama(base_url: str, timeout: float = 2.0) -> bool:
    """检查 Ollama 服务是否可达；任何异常都视为不可达，不向外抛出。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("Ollama 不可达：%s", exc)
        return False


def _field_name(loc: tuple) -> str:
    return ".".join(str(p) for p in loc if p not in ("body", "path", "query"))


def register_error_handlers(app: FastAPI) -> None:
    """所有错误都返回 {"detail": 中文说明}，前端可以直接展示。"""

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = HTTP_MESSAGES.get(exc.status_code, exc.detail)
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({_field_name(e["loc"]) for e in exc.errors()} - {""})
        detail = "请求参数不合法" + (f"：{'、'.join(fields)}" if fields else "")
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的异常：%s %s", request.method, request.url.path)
        return JSONResponse({"detail": "服务内部错误，请稍后再试"}, status_code=500)


def create_app(service_factory: Callable[[], ChatService] | None = None) -> FastAPI:
    """应用工厂：创建并配置 FastAPI 实例。

    service_factory 创建问答服务，默认用真实模型和本地索引；测试时传入假模型组装的服务。
    服务在第一次调用问答接口时才创建。
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if app.state.service is not None:
            app.state.service.close()

    app = FastAPI(title="KiwiGuide", version=__version__, description="新西兰留学生生活助手",
                  lifespan=lifespan)
    app.state.service = None
    app.state.service_factory = service_factory or (lambda: build_service(get_settings()))
    register_error_handlers(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.info("%s %s -> 500（%.0f 毫秒）", request.method, request.url.path, elapsed)
            raise
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("%s %s -> %d（%.0f 毫秒）", request.method, request.url.path,
                    response.status_code, elapsed)
        return response

    @app.get("/health", summary="服务健康检查")
    async def health() -> dict:
        ollama_ok = await check_ollama(get_settings().ollama_base_url)
        return {
            "status": "ok" if ollama_ok else "degraded",
            "version": __version__,
            "ollama": ollama_ok,
        }

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")

    app.include_router(router)
    return app


app = create_app()
