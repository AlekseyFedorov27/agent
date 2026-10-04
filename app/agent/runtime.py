from typing import Any, Awaitable, Callable

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.schemas import MessageOut
from app.runs.models import EventType


# --------------------------------------------------------------------------- #
# Сериализация сообщений
# --------------------------------------------------------------------------- #

def _content_to_str(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def _message_to_dict(m: Any) -> dict:
    return {
        "type": getattr(m, "type", m.__class__.__name__.lower()),
        "content": _content_to_str(getattr(m, "content", "")),
        "tool_calls": getattr(m, "tool_calls", None) or None,
    }


def _serialize_messages(messages: list) -> list[MessageOut]:
    return [MessageOut(**_message_to_dict(m)) for m in messages]


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #

EventHandler = Callable[[str, dict], Awaitable[None]]


class AgentRuntimeService:
    def __init__(self, graph: CompiledStateGraph):
        self.graph = graph

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    # --- Базовые операции -------------------------------------------------- #

    async def start_run(
        self,
        thread_id: str,
        message: str,
        *,
        user_name: str = "",
        system_prompt: str = "",
    ) -> dict:
        return await self.graph.ainvoke(
            {
                "messages": [HumanMessage(content=message)],
                "user_name": user_name,
                "system_prompt": system_prompt,
            },
            config=self._config(thread_id),
        )

    async def resume_run(self, thread_id: str, resume_value: dict) -> dict:
        return await self.graph.ainvoke(
            Command(resume=resume_value),
            config=self._config(thread_id),
        )

    async def get_state(self, thread_id: str):
        return await self.graph.aget_state(self._config(thread_id))

    @staticmethod
    def get_pending_interrupts(state) -> list[dict]:
        result: list[dict] = []
        for task in (getattr(state, "tasks", None) or []):
            for intr in (getattr(task, "interrupts", None) or []):
                result.append(
                    {
                        "id": getattr(intr, "id", None),
                        "value": getattr(intr, "value", None),
                    }
                )
        return result

    # --- Чистка чекпоинтов ------------------------------------------------- #

    async def delete_thread_checkpoints(self, thread_id: str) -> None:
        """
        Чистит LangGraph-чекпоинты по thread_id.
        У AsyncPostgresSaver есть метод adelete_thread; если его нет —
        просто ничего не делаем (не критично, thread_id — UUID и не переиспользуется).
        """
        saver = getattr(self.graph, "checkpointer", None)
        if saver is None:
            return
        deleter = getattr(saver, "adelete_thread", None)
        if deleter is None:
            return
        try:
            await deleter(thread_id)
        except Exception:
            # Не валим всю операцию из-за чекпоинтов
            pass

    # --- Streaming --------------------------------------------------------- #

    async def stream_run(
        self,
        thread_id: str,
        message: str,
        *,
        on_event: EventHandler,
        user_name: str = "",
        system_prompt: str = "",
    ) -> dict:
        """
        Запускает граф со стримингом.
        on_event вызывается на каждый update от графа.
        Возвращает финальный state.values.
        """
        async for chunk in self.graph.astream(
            {
                "messages": [HumanMessage(content=message)],
                "user_name": user_name,
                "system_prompt": system_prompt,
            },
            config=self._config(thread_id),
            stream_mode="updates",
        ):
            # chunk = {node_name: node_output}
            for node_name, node_output in chunk.items():
                if not isinstance(node_output, dict):
                    continue
                messages = node_output.get("messages") or []
                payload = {
                    "node": node_name,
                    "messages": [_message_to_dict(m) for m in messages],
                }
                if node_name == "llm":
                    event_type = EventType.LLM_END
                elif node_name == "tools":
                    event_type = EventType.TOOL_END
                else:
                    event_type = EventType.NODE_UPDATE
                await on_event(event_type, payload)

        state = await self.get_state(thread_id)
        return dict(state.values) if state.values else {}