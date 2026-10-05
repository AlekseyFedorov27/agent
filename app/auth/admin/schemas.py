import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.auth.schemas import Password

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: Password
    name: str = Field(min_length=1, max_length=120)
    position: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=8000)
    is_active: bool = True
    is_superuser: bool = False


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    position: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=8000)
    is_active: bool | None = None
    is_superuser: bool | None = None
    password: Password | None = None


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    position: str | None
    system_prompt: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime