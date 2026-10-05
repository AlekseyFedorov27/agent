from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id) -> User | None:
    return await session.get(User, user_id)


async def register_user(
    session: AsyncSession,
    email: str,
    password: str,
    *,
    name: str | None = None,
    position: str | None = None,
) -> User:
    email = email.lower()
    existing = await get_user_by_email(session, email)
    if existing is not None:
        raise ConflictError("User with this email already exists")

    # Fallback совпадает с логикой миграции 3fa0a183de45:
    # name = local-part email, если явное имя не передали.
    resolved_name = (name.strip() if name else "") or email.split("@", 1)[0]

    user = User(
        email=email,
        name=resolved_name,
        position=(position.strip() if position else None),
        hashed_password=hash_password(password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email.lower())
    if user is None or not verify_password(password, user.hashed_password):
        # Одинаковое сообщение для обоих случаев — не подсказываем атакующему,
        # существует ли пользователь.
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("User is inactive")
    return user