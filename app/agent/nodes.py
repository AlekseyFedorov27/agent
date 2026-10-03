from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent.llm import get_llm
from app.agent.state import AgentState
from app.agent.tools import calculator

SYSTEM_PROMPT = """Ты — ассистент-калькулятор. Отвечай на русском языке.

ПРАВИЛА:
1. Для любых арифметических выражений обязательно вызывай инструмент `calculator`.
   Никогда не считай в уме.
2. Всегда форматируй ответ в Markdown:
   - если шагов больше одного — нумерованный список;
   - формулы и промежуточные результаты — инлайн-кодом: `(123 + 456) * 7`;
   - итоговый ответ — **жирным**;
   - заголовки — через `##` (например, «## Решение», «## Ответ»).
3. Не оборачивай весь ответ в один блок кода — только формулы/код.
4. Отвечай кратко: без воды, без повторов условия задачи.

ПРИМЕР ОТВЕТА:

## Решение
1. Выражение: `(123 + 456) * 7`
2. Промежуточный результат: `579`
3. Итог: **4053**

## Ответ
**4053**
"""

TOOLS = [calculator]
tool_node = ToolNode(TOOLS)


def _ensure_markdown(text: str) -> str:
    """
    Мягкая страховка: если модель вернула plain text, разбиваем его
    на абзацы, чтобы markdown-it сделал <p>, а не склеил в одну строку.
    Уже размеченный текст не трогаем.
    """
    if not text or not text.strip():
        return text

    import re
    # Уже есть Markdown? — не трогаем
    if re.search(r"(^#{1,6} |\*\*.+?\*\*|```|^\s*[-*] |^\s*\d+\. )", text, re.M):
        return text

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return "\n\n".join(paragraphs)


def llm_node(state: AgentState) -> dict:
    llm = get_llm().bind_tools(TOOLS)
    messages = state["messages"]

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

    response = llm.invoke(messages)

    # Применяем только к текстовым ответам.
    # Если response содержит tool_calls — content часто пустой,
    # и трогать его нельзя.
    if not getattr(response, "tool_calls", None) and response.content:
        response.content = _ensure_markdown(response.content)

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