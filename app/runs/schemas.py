import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: str
    status: str
    input: dict[str, Any] 
    created_at: datetime
    completed_at: datetime | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime


class AdminRunOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    user_name: str
    thread_id: str
    status: str
    input: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None


class AdminRunListOut(BaseModel):
    items: list[AdminRunOut]
    total: int


class AdminRunDetailOut(AdminRunOut):
    events: list["EventOut"]


# Разрешаем forward-ref: EventOut объявлен выше, но это защита от перестановок.
AdminRunDetailOut.model_rebuild()