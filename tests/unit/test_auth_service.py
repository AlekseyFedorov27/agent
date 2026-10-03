"""Unit-тесты для app.auth.service."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import (
    authenticate_user,
    get_user_by_email,
    get_user_by_id,
    register_user,
)
from app.core.exceptions import ConflictError, UnauthorizedError


class TestRegister:
    async def test_register_creates_user(self, test_session: AsyncSession) -> None:
        user = await register_user(test_session, "new@test.com", "password123")
        assert user.id is not None
        assert user.email == "new@test.com"
        assert user.is_active is True
        assert user.is_superuser is False
        assert user.hashed_password != "password123"

    async def test_register_normalizes_email_to_lowercase(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "Mixed@Case.com", "password123")
        assert user.email == "mixed@case.com"

    async def test_register_rejects_duplicate_email(
        self, test_session: AsyncSession
    ) -> None:
        await register_user(test_session, "dup@test.com", "password123")
        with pytest.raises(ConflictError):
            await register_user(test_session, "dup@test.com", "another")

    async def test_register_duplicate_case_insensitive(
        self, test_session: AsyncSession
    ) -> None:
        await register_user(test_session, "dup@test.com", "password123")
        with pytest.raises(ConflictError):
            await register_user(test_session, "DUP@test.com", "password123")


class TestGetUser:
    async def test_get_by_email_found(self, test_session: AsyncSession) -> None:
        created = await register_user(test_session, "find@test.com", "password123")
        found = await get_user_by_email(test_session, "find@test.com")
        assert found is not None
        assert found.id == created.id

    async def test_get_by_email_not_found(self, test_session: AsyncSession) -> None:
        assert await get_user_by_email(test_session, "no@test.com") is None

    async def test_get_by_id(self, test_session: AsyncSession) -> None:
        created = await register_user(test_session, "byid@test.com", "password123")
        found = await get_user_by_id(test_session, created.id)
        assert found is not None
        assert found.email == "byid@test.com"


class TestAuthenticate:
    async def test_authenticate_success(self, test_session: AsyncSession) -> None:
        await register_user(test_session, "auth@test.com", "password123")
        user = await authenticate_user(test_session, "auth@test.com", "password123")
        assert user.email == "auth@test.com"

    async def test_authenticate_wrong_password(
        self, test_session: AsyncSession
    ) -> None:
        await register_user(test_session, "auth@test.com", "password123")
        with pytest.raises(UnauthorizedError):
            await authenticate_user(test_session, "auth@test.com", "wrong")

    async def test_authenticate_unknown_email(
        self, test_session: AsyncSession
    ) -> None:
        with pytest.raises(UnauthorizedError):
            await authenticate_user(test_session, "nobody@test.com", "password123")

    async def test_authenticate_inactive_user(
        self, test_session: AsyncSession
    ) -> None:
        user = await register_user(test_session, "inactive@test.com", "password123")
        user.is_active = False
        await test_session.commit()

        with pytest.raises(UnauthorizedError, match="inactive"):
            await authenticate_user(test_session, "inactive@test.com", "password123")