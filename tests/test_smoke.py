"""Smoke-тесты: проверяют, что инфраструктура тестов работает."""

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"


async def test_register_and_login(client: AsyncClient) -> None:
    # Register
    r = await client.post(
        "/auth/register",
        json={
            "email": "smoke@test.com",
            "password": "password123",
            "name": "Smoke User",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "smoke@test.com"

    # Login
    r = await client.post(
        "/auth/login",
        json={"email": "smoke@test.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()

    # /me
    token = r.json()["access_token"]
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "smoke@test.com"


async def test_mock_llm_simple(patch_llm, authenticated_client: AsyncClient) -> None:
    from langchain_core.messages import AIMessage

    patch_llm([AIMessage(content="Привет!")])

    r = await authenticated_client.post(
        "/agent/run",
        json={"message": "Привет!"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    # Последнее сообщение — ответ LLM
    assert body["messages"][-1]["content"] == "Привет!"