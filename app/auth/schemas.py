import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Annotated
from pydantic import AfterValidator
from app.core.security import validate_password_bytes

Password = Annotated[
    str,
    Field(min_length=8, max_length=72),
    AfterValidator(validate_password_bytes),
]

class UserCreate(BaseModel):
    email: EmailStr
    password: Password
    name: str = Field(min_length=1, max_length=120)
    position: str | None = Field(default=None, max_length=120)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    position: str | None
    system_prompt: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str