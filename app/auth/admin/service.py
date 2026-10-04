import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.service import get_user_by_email
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password


async def list_users(session: AsyncSession) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    name: str,
    position: str | None = None,
    system_prompt: str | None = None,
    is_active: bool = True,
    is_superuser: bool = False,
) -> User:
    email = email.lower()
    if await get_user_by_email(session, email) is not None:
        raise ConflictError("User with this email already exists")

    user = User(
        email=email,
        name=name.strip(),
        position=(position.strip() if position else None),
        system_prompt=system_prompt or None,
        hashed_password=hash_password(password),
        is_active=is_active,
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    user: User,
    *,
    name: str | None = None,
    position: str | None = None,
    system_prompt: str | None = None,
    is_active: bool | None = None,
    is_superuser: bool | None = None,
    password: str | None = None,
) -> User:
    if name is not None:
        user.name = name.strip()
    if position is not None:
        user.position = position.strip() or None
    if system_prompt is not None:
        user.system_prompt = system_prompt or None
    if is_active is not None:
        user.is_active = is_active
    if is_superuser is not None:
        user.is_superuser = is_superuser
    if password:
        user.hashed_password = hash_password(password)

    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()