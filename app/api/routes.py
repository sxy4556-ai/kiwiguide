"""问答、来源和索引更新接口。"""

import json
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.concurrency import iterate_in_threadpool, run_in_threadpool
from sse_starlette import EventSourceResponse

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    RefreshStatus,
    ResumeRequest,
    SourcesResponse,
)
from app.api.service import ChatService, ServiceError

router = APIRouter()
_build_lock = threading.Lock()

SERVICE_UNAVAILABLE = "问答服务暂不可用，请确认 Ollama 已启动、向量模型已安装并已建好索引"
ERRORS = {
    409: {"model": ErrorResponse, "description": "状态冲突"},
    503: {"model": ErrorResponse, "description": "问答服务暂不可用"},
}


def _get_service(request: Request) -> ChatService:
    """第一次用到时才创建服务：Ollama 没启动时 /health 和首页仍然可以访问。"""
    state = request.app.state
    if state.service is None:
        with _build_lock:
            if state.service is None:
                try:
                    state.service = state.service_factory()
                except Exception as e:
                    raise ServiceError(503, SERVICE_UNAVAILABLE) from e
    return state.service


Service = Annotated[ChatService, Depends(_get_service)]
ThreadIdPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$", description="会话 ID")]


@router.post("/chat", response_model=ChatResponse, responses=ERRORS, summary="提问")
async def chat(body: ChatRequest, service: Service) -> dict:
    return await run_in_threadpool(service.chat, body.question, body.thread_id)


@router.post("/chat/{thread_id}/resume", response_model=ChatResponse, responses=ERRORS,
             summary="回答反问，从断点继续")
async def resume_chat(thread_id: ThreadIdPath, body: ResumeRequest, service: Service) -> dict:
    return await run_in_threadpool(service.resume, thread_id, body.answer)


@router.post("/chat/stream", responses=ERRORS, summary="流式提问（SSE）")
async def chat_stream(body: ChatRequest, service: Service) -> EventSourceResponse:
    """事件依次为 start、progress（节点进度）、token（生成中的文字）、answer（完整回答）、
    citations（引用列表）、done；需要反问时以 clarification 代替 answer 和 citations，
    出错时发送 error。"""

    async def events():
        async for name, data in iterate_in_threadpool(service.stream(body.question,
                                                                     body.thread_id)):
            yield {"event": name, "data": json.dumps(data, ensure_ascii=False)}

    return EventSourceResponse(events())


@router.get("/sources", response_model=SourcesResponse, responses=ERRORS,
            summary="已索引的来源列表")
async def sources(service: Service) -> dict:
    items = await run_in_threadpool(service.sources)
    return {"total": len(items), "sources": items}


@router.post("/ingest/refresh", response_model=RefreshStatus, responses=ERRORS,
             status_code=status.HTTP_202_ACCEPTED, summary="后台重新抓取并增量更新索引")
async def refresh(service: Service) -> dict:
    if not service.refresh_job.start():
        raise ServiceError(409, "更新任务已经在运行，请稍后用 GET /ingest/refresh 查看进度")
    return service.refresh_job.status()


@router.get("/ingest/refresh", response_model=RefreshStatus, responses=ERRORS,
            summary="查看更新任务的状态")
async def refresh_status(service: Service) -> dict:
    return service.refresh_job.status()
