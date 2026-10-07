from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    approval_node,
    llm_node,
    route_after_approval,
    route_after_llm,
    tool_node,
)
from app.agent.state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("llm", llm_node)
    builder.add_node("approval", approval_node)
    builder.add_node("tools", tool_node)

    builder.add_edge(START, "llm")
    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {"approval": "approval", "end": END},
    )
    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"tools": "tools", "llm": "llm"},
    )
    builder.add_edge("tools", "llm")

    if isinstance(checkpointer, BaseCheckpointSaver):
        saver = checkpointer
    else:
        saver = InMemorySaver()

    return builder.compile(checkpointer=saver)