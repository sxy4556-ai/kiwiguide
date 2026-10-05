"""接口的请求和响应模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ThreadId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class ChatRequest(BaseModel):
    question: Text = Field(description="问题")
    thread_id: ThreadId | None = Field(default=None, description="会话 ID；不传时新建会话")


class ResumeRequest(BaseModel):
    answer: Text = Field(description="对反问的回答")


class CitationOut(BaseModel):
    index: int
    title: str
    url: str
    retrieved_at: str


class ChatResponse(BaseModel):
    thread_id: str
    status: Literal["answered", "needs_clarification"]
    answer: str | None = None
    citations: list[CitationOut] = []
    clarification_question: str | None = None


class SourceOut(BaseModel):
    topic: str
    title: str
    url: str
    retrieved_at: str


class SourcesResponse(BaseModel):
    total: int
    sources: list[SourceOut]


class RefreshStatus(BaseModel):
    status: Literal["idle", "running", "succeeded", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    message: str = ""


class ErrorResponse(BaseModel):
    detail: str
