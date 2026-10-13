from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.nodes import NODES
from app.nodes.ask_user import route_after_triage
from app.nodes.budget_check import route_after_budget
from app.agent.state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("triage", NODES["triage"])
    builder.add_node("ask_user", NODES["ask_user"])
    builder.add_node("research", NODES["research"])
    builder.add_node("plan", NODES["plan"])
    builder.add_node("replan", NODES["replan"])
    builder.add_node("budget_check", NODES["budget_check"])

    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage",
        route_after_triage,
        {"ask_user": "ask_user", "research": "research"},
    )

    builder.add_edge("ask_user", END)

    builder.add_edge("research", "plan")
    builder.add_edge("plan", "budget_check")
    builder.add_conditional_edges(
        "budget_check",
        route_after_budget,
        {"end": END, "replan": "replan"},
    )
    builder.add_edge("replan", "budget_check")

    saver = (
        checkpointer if isinstance(checkpointer, BaseCheckpointSaver)
        else InMemorySaver()
    )
    return builder.compile(checkpointer=saver)