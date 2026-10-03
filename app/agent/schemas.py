import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = None


class MessageOut(BaseModel):
    type: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None


class RunResponse(BaseModel):
    run_id: uuid.UUID | None = None
    thread_id: str
    status: Literal["completed", "interrupted"]
    messages: list[MessageOut]
    pending_approval_id: uuid.UUID | None = None


class ThreadStatusResponse(BaseModel):
    thread_id: str
    next_nodes: list[str]
    messages: list[MessageOut]