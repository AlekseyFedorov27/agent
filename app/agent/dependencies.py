from fastapi import Request

from app.agent.runtime import AgentRuntimeService


def get_runtime(request: Request) -> AgentRuntimeService:
    return request.app.state.runtime