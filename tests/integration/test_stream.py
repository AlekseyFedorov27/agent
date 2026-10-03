"""Integration-тесты SSE-стриминга через POST /agent/stream."""

import json

from httpx import AsyncClient
from langchain_core.messages import AIMessage
from tests.conftest import make_tool_call


async def _read_sse_events(response) -> list[dict]:
    """
    Парсит SSE-поток в список событий: [{event: str, data: dict}, ...]
    """
    events: list[dict] = []
    current_event: str | None = None
    current_data: str | None = None

    async for line in response.aiter_lines():
        if not line:
            if current_event is not None:
                events.append({
                    "event": current_event,
                    "data": json.loads(current_data) if current_data else {},
                })
                current_event = None
                current_data = None
            continue

        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            current_data = line[len("data: "):]

    # Хвост без пустой строки в конце
    if current_event is not None:
        events.append({
            "event": current_event,
            "data": json.loads(current_data) if current_data else {},
        })

    return events


class TestStreamSimple:
    async def test_simple_stream_completes(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([AIMessage(content="Привет!")])

        async with authenticated_client.stream(
            "POST",
            "/agent/stream",
            json={"message": "Привет!"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = await _read_sse_events(response)

        kinds = [e["event"] for e in events]
        assert "run_started" in kinds
        assert kinds[-1] == "completed"

        # run_started содержит run_id и thread_id
        started = next(e for e in events if e["event"] == "run_started")
        assert "run_id" in started["data"]
        assert "thread_id" in started["data"]

        # completed содержит финальные messages
        completed = next(e for e in events if e["event"] == "completed")
        assert completed["data"]["messages"][-1]["content"] == "Привет!"


class TestStreamInterrupt:
    async def test_stream_interrupts_on_tool_call(
        self, patch_llm, authenticated_client: AsyncClient
    ) -> None:
        patch_llm([
            AIMessage(
                content="",
                tool_calls=[make_tool_call("calculator", {"expression": "2 + 2"})],
            ),
        ])

        async with authenticated_client.stream(
            "POST",
            "/agent/stream",
            json={"message": "Посчитай 2 + 2"},
        ) as response:
            assert response.status_code == 200
            events = await _read_sse_events(response)

        kinds = [e["event"] for e in events]
        assert "run_started" in kinds
        assert "interrupt" in kinds
        assert "interrupted" in kinds
        assert kinds[-1] == "interrupted"

        # В interrupted есть pending_approval_id
        interrupted = next(e for e in events if e["event"] == "interrupted")
        assert interrupted["data"]["pending_approval_id"] is not None

        # В interrupt payload — tool_calls
        interrupt_ev = next(e for e in events if e["event"] == "interrupt")
        payload = interrupt_ev["data"]["value"]
        assert payload["type"] == "tool_approval"
        assert payload["tool_calls"][0]["name"] == "calculator"


class TestStreamAuth:
    async def test_stream_requires_auth(self, client: AsyncClient) -> None:
        r = await client.post("/agent/stream", json={"message": "hi"})
        assert r.status_code == 401