# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.checkpointer import close_checkpointer, init_checkpointer
from app.agent.graph import build_graph
from app.agent.router import router as agent_router
from app.agent.runtime import AgentRuntimeService
from app.auth.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.config import get_settings
from app.core.database import dispose_db
from app.core.telemetry import setup_telemetry
from app.hitl.router import router as hitl_router
from app.runs.router import router as runs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. OpenTelemetry — ПЕРВЫМ делом, чтобы FastAPI и HTTPX успели
    #    инструментироваться до первого запроса.
    setup_telemetry(app)

    # 2. LangGraph checkpointer — держим открытым на весь lifespan.
    saver = await init_checkpointer()
    app.state.runtime = AgentRuntimeService(build_graph(saver))

    yield

    # 3. Graceful shutdown.
    await close_checkpointer()
    await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # --- health ---
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(agent_router)
    app.include_router(hitl_router)
    app.include_router(runs_router)

    return app


app = create_app()