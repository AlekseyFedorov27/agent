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
from app.hitl import service as hitl_service
from app.runs import service as runs_service
from app.runs.models import EventType, RunStatus

router = APIRouter(prefix="/agent", tags=["agent"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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

    run = await runs_service.create_run(
        session,
        user_id=user.id,
        thread_id=thread_id,
        input_payload={"message": data.message},
    )

    result = await runtime.start_run(thread_id, data.message)
    state = await runtime.get_state(thread_id)
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
    message = data.message

    async def event_generator():
        # Отдельная сессия: request-scoped закроется до окончания стрима.
        session_factory = get_session_factory()
        async with session_factory() as session:
            run = await runs_service.create_run(
                session,
                user_id=user_id,
                thread_id=thread_id,
                input_payload={"message": message},
            )

            yield _sse("run_started", {
                "run_id": str(run.id),
                "thread_id": thread_id,
            })

            async def on_event(event_type: str, payload: dict) -> None:
                await runs_service.add_event(
                    session, run_id=run.id, type=event_type, payload=payload
                )

            try:
                await runtime.stream_run(thread_id, message, on_event=on_event)
                state = await runtime.get_state(thread_id)
                next_nodes = list(state.next) if state.next else []

                if next_nodes:
                    await runs_service.update_status(session, run, RunStatus.INTERRUPTED)

                    pending_id: uuid.UUID | None = None
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
                    await runs_service.update_status(session, run, RunStatus.COMPLETED)
                    messages = state.values.get("messages", []) if state.values else []
                    await runs_service.add_event(
                        session, run_id=run.id, type=EventType.END,
                        payload={"messages": [_message_to_dict(m) for m in messages]},
                    )
                    yield _sse("completed", {
                        "thread_id": thread_id,
                        "messages": [_message_to_dict(m) for m in messages],
                    })
            except Exception as e:
                await runs_service.update_status(session, run, RunStatus.FAILED)
                await runs_service.add_event(
                    session, run_id=run.id, type=EventType.ERROR,
                    payload={"error": str(e), "type": type(e).__name__},
                )
                yield _sse("error", {"detail": str(e), "type": type(e).__name__})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # для nginx
        },
    )


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

@router.get("/status/{thread_id}", response_model=ThreadStatusResponse)
async def get_thread_status(
    thread_id: str,
    user: CurrentUser,
    runtime: Runtime,
) -> ThreadStatusResponse:
    state = await runtime.get_state(thread_id)
    messages = state.values.get("messages", []) if state.values else []
    return ThreadStatusResponse(
        thread_id=thread_id,
        next_nodes=list(state.next) if state.next else [],
        messages=_serialize_messages(messages),
    )