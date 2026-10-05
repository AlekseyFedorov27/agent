import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession


from app.auth.dependencies import CurrentUser
from app.auth.schemas import (
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserPublic,
)
from app.auth.service import authenticate_user, register_user, get_user_by_id
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user_id: str) -> TokenPair:
    sub = str(user_id)
    return TokenPair(
        access_token=create_access_token(sub),
        refresh_token=create_refresh_token(sub),
    )


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserPublic:
    user = await register_user(
        session,
        data.email,
        data.password,
        name=data.name,
        position=data.position,
    )
    return UserPublic.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(
    data: UserLogin,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    user = await authenticate_user(session, data.email, data.password)
    return _issue_tokens(user.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    data: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    try:
        payload = decode_token(data.refresh_token, expected_type="refresh")
    except JWTError as e:
        raise UnauthorizedError("Invalid or expired refresh token") from e

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Invalid refresh token payload")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as e:
        raise UnauthorizedError("Invalid user id in token") from e

    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    return _issue_tokens(str(user.id))


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)