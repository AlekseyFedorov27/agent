import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: str
    status: str
    payload: dict[str, Any]
    comment: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=2000)