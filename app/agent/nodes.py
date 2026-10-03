from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent.llm import get_llm
from app.agent.state import AgentState
from app.agent.tools import calculator

SYSTEM_PROMPT = (
    "Ты — ассистент, который умеет считать. "
    "Для любых арифметических выражений обязательно используй инструмент "
    "`calculator`. Не считай в уме. Отвечай кратко и по делу на русском."
)

TOOLS = [calculator]
tool_node = ToolNode(TOOLS)


def llm_node(state: AgentState) -> dict:
    llm = get_llm().bind_tools(TOOLS)
    messages = state["messages"]

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

    response = llm.invoke(messages)
    return {"messages": [response]}


def route_after_llm(state: AgentState) -> str:
    """Если LLM запросил tool_call → идём на approval, иначе — в END."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return "end"


def approval_node(state: AgentState) -> dict:
    """
    Точка Human-in-the-Loop.
    При первом заходе вызывает interrupt() и граф останавливается.
    При resume — interrupt() вернёт значение из Command(resume=...).
    """
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    decision = interrupt(
        {
            "type": "tool_approval",
            "tool_calls": [
                {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                for tc in tool_calls
            ],
        }
    )

    approved = (
        bool(decision.get("approved"))
        if isinstance(decision, dict)
        else bool(decision)
    )

    if approved:
        return {"approval_decision": "approved"}

    # Отказ: генерируем ToolMessage-заглушки, чтобы LLM знал,
    # что инструмент не был вызван.
    denial_messages = [
        ToolMessage(
            content="Пользователь отклонил вызов инструмента.",
            tool_call_id=tc["id"],
        )
        for tc in tool_calls
    ]
    return {"messages": denial_messages, "approval_decision": "rejected"}


def route_after_approval(state: AgentState) -> str:
    if state.get("approval_decision") == "approved":
        return "tools"
    return "llm"