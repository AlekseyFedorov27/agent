import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import service
from app.auth.admin.schemas import AdminUserCreate, AdminUserOut, AdminUserUpdate
from app.auth.dependencies import require_superuser
from app.auth.models import User
from app.core.database import get_db
from app.core.exceptions import ForbiddenError

# Все роуты под /admin требуют superuser
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_superuser)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
AdminUser = Annotated[User, Depends(require_superuser)]


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    _: AdminUser,
    session: DbSession,
) -> list[AdminUserOut]:
    users = await service.list_users(session)
    return [AdminUserOut.model_validate(u) for u in users]


@router.post(
    "/users",
    response_model=AdminUserOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    data: AdminUserCreate,
    _: AdminUser,
    session: DbSession,
) -> AdminUserOut:
    user = await service.create_user(
        session,
        email=data.email,
        password=data.password,
        name=data.name,
        position=data.position,
        system_prompt=data.system_prompt,
        is_active=data.is_active,
        is_superuser=data.is_superuser,
    )
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    admin: AdminUser,
    session: DbSession,
) -> AdminUserOut:
    user = await service.get_user(session, user_id)

    # защита: админ не может снять с себя права и выключить себя
    if user.id == admin.id:
        if data.is_superuser is False:
            raise ForbiddenError("Cannot revoke your own superuser rights")
        if data.is_active is False:
            raise ForbiddenError("Cannot deactivate yourself")

    user = await service.update_user(
        session,
        user,
        name=data.name,
        position=data.position,
        system_prompt=data.system_prompt,
        is_active=data.is_active,
        is_superuser=data.is_superuser,
        password=data.password,
    )
    return AdminUserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    admin: AdminUser,
    session: DbSession,
) -> Response:
    if user_id == admin.id:
        raise ForbiddenError("Cannot delete yourself")
    user = await service.get_user(session, user_id)
    await service.delete_user(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)