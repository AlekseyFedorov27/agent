from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from app.agent.state import AgentState
from app.nodes import NODES
from app.nodes.ask_user import route_after_triage
from app.nodes.budget_check import route_after_budget
from app.nodes.plan_approval import route_after_plan_approval


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("triage", NODES["triage"])
    builder.add_node("ask_user", NODES["ask_user"])
    builder.add_node("research", NODES["research"])
    builder.add_node("plan", NODES["plan"])
    builder.add_node("replan", NODES["replan"])
    builder.add_node("budget_check", NODES["budget_check"])
    builder.add_node("plan_approval", NODES["plan_approval"])

    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage",
        route_after_triage,
        {"ask_user": "ask_user", "research": "research"},
    )
    builder.add_edge("ask_user", END)

    builder.add_edge("research", "plan")
    builder.add_edge("plan", "budget_check")

    # budget_check теперь ведёт не в END, а в plan_approval,
    # когда бюджет в порядке / попытки исчерпаны.
    builder.add_conditional_edges(
        "budget_check",
        route_after_budget,
        {"end": "plan_approval", "replan": "replan"},
    )

    builder.add_conditional_edges(
        "plan_approval",
        route_after_plan_approval,
        {"end": END, "replan": "replan"},
    )

    builder.add_edge("replan", "budget_check")

    saver = (
        checkpointer if isinstance(checkpointer, BaseCheckpointSaver)
        else InMemorySaver()
    )
    return builder.compile(checkpointer=saver)