from typing import Any
from app.agent.llm import get_llm
from app.agent.state import AgentState
from langchain_core.messages import HumanMessage, SystemMessage
from app.agent.state import AgentState

ASK_SYSTEM_PROMPT = (
    "Ты — ассистент по планированию путешествий. "
    "Задай ОДИН вежливый уточняющий вопрос про самое важное "
    "из недостающих полей. Не перечисляй всё сразу. "
    "Отвечай одним коротким вопросом."
)

def ask_user(state: AgentState) -> dict[str, Any]:
    llm = get_llm()
    result = llm.invoke([
        SystemMessage(content=ASK_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Уже собрано: {state.get('request')}\n"
            f"Не хватает: {state.get('missing_fields')}\n"
            "Сформулируй вопрос."
        )),
    ])
    return {"messages": [result]}


def route_after_triage(state: AgentState) -> str:
    if state.get("missing_fields"):
        return "ask_user"
    return "research"