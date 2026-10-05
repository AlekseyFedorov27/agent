from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent.llm import get_llm
from app.agent.state import AgentState
from app.agent.tools import calculator

BASE_SYSTEM_PROMPT = """Отвечай на русском языке.


ПРАВИЛА:
1. Для любых арифметических выражений обязательно вызывай инструмент `calculator`.
   Никогда не считай в уме.
2. Результат инструмента — истина. Копируй его в ответ дословно.
3. ОБРАЗЕЦ ПРАВИЛЬНОГО ОТВЕТА (копируй эту структуру):

# Сравнение фреймворков для ML

**PyTorch** и **TensorFlow** — два основных фреймворка для глубокого обучения.

## Особенности

- **PyTorch** — динамический граф, популярен в исследованиях
- **TensorFlow** — статический граф, сильный продакшн-тулинг
- **Оба** поддерживают GPU и распределённое обучение

## Сравнение

| Параметр | PyTorch | TensorFlow |
|---|---|---|
| Граф | Динамический | Статический |
| Порог входа | Низкий | Средний |
| Продакшн | Ок | Лучше |

---

ПРАВИЛА:
1. Разделы — через `##`, НЕ через `**жирный**`.
2. Списки — через `-`, НЕ через `•` или `●`.
3. Таблицы — через `|` и разделитель `|---|---|` без пустых строк между рядами.
4. Жирный `**...**` — только внутри абзаца для акцента, НЕ для заголовков.
5. Никаких вводных слов, извинений, дисклеймеров.
6. Длина не ограничена.


## Решение
Выражение: `<точное выражение>`
Результат: `<точное значение из calculator>`

## Ответ
**<точное значение>**

4. Отвечай кратко, без воды.
"""

TOOLS = [calculator]
tool_node = ToolNode(TOOLS)


def _compose_system_prompt(user_name: str, user_prompt: str) -> str:
    parts: list[str] = [BASE_SYSTEM_PROMPT]

    if user_name:
        parts.append(
            f"Имя пользователя: {user_name}. "
            f"Обращайся к нему по имени, когда это уместно."
        )

    if user_prompt and user_prompt.strip():
        parts.append(
            "ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ОТ ПОЛЬЗОВАТЕЛЯ "
            "(имеют приоритет над общими правилами, кроме безопасности):\n"
            + user_prompt.strip()
        )

    return "\n\n".join(parts)


async def llm_node(state: AgentState) -> dict:
    llm = get_llm().bind_tools(TOOLS)
    messages = state["messages"]

    user_name = state.get("user_name") or ""
    user_prompt = state.get("system_prompt") or ""
    system_text = _compose_system_prompt(user_name, user_prompt)

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_text), *messages]
    else:
        messages = [SystemMessage(content=system_text), *messages[1:]]

    response = await llm.ainvoke(messages)

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