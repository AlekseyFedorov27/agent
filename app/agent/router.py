import asyncio
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.dependencies import get_runtime
from app.agent.runtime import (
    AgentRuntimeService,
    _message_to_dict,
    _serialize_messages,
)
from app.agent.schemas import RunRequest, RunResponse, ThreadStatusResponse
from app.auth.dependencies import CurrentUser
from app.core.database import get_db, get_session_factory
from app.core.telemetry import enrich_current_span
from app.hitl import service as hitl_service
from app.runs import service as runs_service
from app.runs.models import EventType, RunStatus

router = APIRouter(prefix="/agent", tags=["agent"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _fail_if_running(run_id: uuid.UUID, error: str, error_type: str) -> None:
    """
    Помечает run как failed, только если он всё ещё running.
    Используется при обрыве соединения клиентом: к этому моменту
    исходная сессия может быть в неопределённом состоянии,
    поэтому открываем отдельную.
    """
    factory = get_session_factory()
    async with factory() as s:
        run = await runs_service.get_run(s, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            return
        await runs_service.update_status(s, run, RunStatus.FAILED)
        await runs_service.add_event(
            s, run_id=run_id, type=EventType.ERROR,
            payload={"error": error, "type": error_type},
        )


# --------------------------------------------------------------------------- #
# Sync run
# --------------------------------------------------------------------------- #

@router.post("/run", response_model=RunResponse)
async def run_agent(
    data: RunRequest,
    user: CurrentUser,
    session: DbSession,
    runtime: Runtime,
) -> RunResponse:
    thread_id = data.thread_id or str(uuid.uuid4())

    if data.thread_id:
        await runs_service.assert_thread_owner(
            session, user_id=user.id, thread_id=thread_id
        )

    run = await runs_service.create_run(
        session,
        user_id=user.id,
        thread_id=thread_id,
        input_payload={"message": data.message},
    )

    # Обогащаем текущий HTTP-спан бизнес-атрибутами,
    # чтобы в Jaeger можно было фильтровать по user_id / thread_id / run_id.
    enrich_current_span(
        user_id=user.id,
        thread_id=thread_id,
        run_id=run.id,
    )

    try:
        result = await runtime.start_run(
            thread_id,
            data.message,
            user_name=user.name,
            system_prompt=user.system_prompt or "",
        )
        state = await runtime.get_state(thread_id)
    except Exception as e:
        await runs_service.update_status(session, run, RunStatus.FAILED)
        await runs_service.add_event(
            session, run_id=run.id, type=EventType.ERROR,
            payload={"error": str(e), "type": type(e).__name__},
        )
        raise

    next_nodes = list(state.next) if state.next else []
    messages = result.get("messages", [])

    pending_id: uuid.UUID | None = None
    if next_nodes:
        await runs_service.update_status(session, run, RunStatus.INTERRUPTED)
        await runs_service.add_event(
            session, run_id=run.id, type=EventType.INTERRUPT,
            payload={"next": next_nodes},
        )
        pending_id = await hitl_service.sync_pending_interrupts(
            session, runtime,
            thread_id=thread_id, user_id=user.id, run_id=run.id,
        )
    else:
        await runs_service.update_status(session, run, RunStatus.COMPLETED)
        await runs_service.add_event(
            session, run_id=run.id, type=EventType.END,
            payload={"messages": [_message_to_dict(m) for m in messages]},
        )

    return RunResponse(
        run_id=run.id,
        thread_id=thread_id,
        status="interrupted" if next_nodes else "completed",
        messages=_serialize_messages(messages),
        pending_approval_id=pending_id,
    )


# --------------------------------------------------------------------------- #
# Streaming run (SSE)
# --------------------------------------------------------------------------- #

@router.post("/stream")
async def stream_agent(
    data: RunRequest,
    user: CurrentUser,
    runtime: Runtime,
) -> StreamingResponse:
    thread_id = data.thread_id or str(uuid.uuid4())
    user_id = user.id
    user_name = user.name
    user_system_prompt = user.system_prompt or ""
    message = data.message

    if data.thread_id:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await runs_service.assert_thread_owner(
                session, user_id=user_id, thread_id=thread_id
            )

    async def event_generator():
        session_factory = get_session_factory()
        async with session_factory() as session:
            run = await runs_service.create_run(
                session,
                user_id=user_id,
                thread_id=thread_id,
                input_payload={"message": message},
            )

            # Обогащаем спан. Атрибуты появятся в Jaeger, если версия
            # instrumentation-fastapi поддерживает enrichment стриминговых
            # ответов. Для /agent/run работает гарантированно.
            enrich_current_span(
                user_id=user_id,
                thread_id=thread_id,
                run_id=run.id,
            )

            # True — как только итоговый статус run записан в БД.
            # Если генератор прервали раньше (клиент отключился),
            # finally пометит run как failed.
            finished = False

            try:
                yield _sse("run_started", {
                    "run_id": str(run.id),
                    "thread_id": thread_id,
                })

                async for evt in runtime.stream_events(
                    thread_id, message,
                    user_name=user_name,
                    system_prompt=user_system_prompt,
                ):
                    if evt["type"] == "token":
                        # Токены не пишем в БД — их слишком много.
                        yield _sse("token", evt["data"])
                    elif evt["type"] == "node":
                        event_type = evt["data"]["event_type"]
                        payload = evt["data"]["payload"]
                        await runs_service.add_event(
                            session, run_id=run.id,
                            type=event_type, payload=payload,
                        )
                        yield _sse("node", payload)

                state = await runtime.get_state(thread_id)
                next_nodes = list(state.next) if state.next else []

                if next_nodes:
                    await runs_service.update_status(
                        session, run, RunStatus.INTERRUPTED
                    )
                    finished = True

                    for intr in runtime.get_pending_interrupts(state):
                        await runs_service.add_event(
                            session, run_id=run.id, type=EventType.INTERRUPT,
                            payload={"interrupt": intr},
                        )
                        yield _sse("interrupt", intr)

                    pending_id = await hitl_service.sync_pending_interrupts(
                        session, runtime,
                        thread_id=thread_id, user_id=user_id, run_id=run.id,
                    )
                    yield _sse("interrupted", {
                        "thread_id": thread_id,
                        "pending_approval_id": str(pending_id) if pending_id else None,
                    })
                else:
                    messages = state.values.get("messages", []) if state.values else []
                    await runs_service.update_status(
                        session, run, RunStatus.COMPLETED
                    )
                    await runs_service.add_event(
                        session, run_id=run.id, type=EventType.END,
                        payload={"messages": [_message_to_dict(m) for m in messages]},
                    )
                    finished = True
                    yield _sse("completed", {
                        "thread_id": thread_id,
                        "messages": [_message_to_dict(m) for m in messages],
                    })

            except Exception as e:
                finished = True
                await runs_service.update_status(session, run, RunStatus.FAILED)
                await runs_service.add_event(
                    session, run_id=run.id, type=EventType.ERROR,
                    payload={"error": str(e), "type": type(e).__name__},
                )
                yield _sse("error", {"detail": str(e), "type": type(e).__name__})

            finally:
                if not finished:
                    # CancelledError / GeneratorExit: клиент закрыл соединение.
                    # shield — чтобы повторная отмена не прервала запись в БД.
                    await asyncio.shield(
                        _fail_if_running(
                            run.id, "Client disconnected", "ClientDisconnect"
                        )
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

@router.get("/status/{thread_id}", response_model=ThreadStatusResponse)
async def get_thread_status(
    thread_id: str,
    user: CurrentUser,
    session: DbSession,
    runtime: Runtime,
) -> ThreadStatusResponse:
    await runs_service.assert_thread_owner(
        session, user_id=user.id, thread_id=thread_id
    )

    state = await runtime.get_state(thread_id)
    messages = state.values.get("messages", []) if state.values else []
    return ThreadStatusResponse(
        thread_id=thread_id,
        next_nodes=list(state.next) if state.next else [],
        messages=_serialize_messages(messages),
    )