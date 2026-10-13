"""Асинхронный узел для уточнения обязательных параметров поездки."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import get_llm
from app.agent.state import AgentState

ASK_SYSTEM_PROMPT = (
    "Ты — ассистент по планированию путешествий. Задай один вежливый и короткий "
    "уточняющий вопрос про самое важное из недостающих полей. Не перечисляй всё сразу."
)


async def ask_user(state: AgentState) -> dict[str, Any]:
    result = await get_llm().ainvoke([
        SystemMessage(content=ASK_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Уже собрано: {state.get('request')}\n"
            f"Не хватает: {state.get('missing_fields')}\n"
            "Сформулируй один вопрос."
        )),
    ])
    return {"messages": [result]}


def route_after_triage(state: AgentState) -> str:
    if state.get("triage_error"):
        return "ask_user"
    return "ask_user" if state.get("missing_fields") else "research"
