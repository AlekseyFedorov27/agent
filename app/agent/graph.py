from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.nodes.ask_user import ask_user, route_after_triage
from app.nodes.budget_check import budget_check, route_after_budget
from app.nodes.plan import plan, replan
from app.nodes.plan_approval import plan_approval, route_after_plan_approval
from app.nodes.research import research
from app.nodes.triage import triage


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("triage", triage)
    builder.add_node("ask_user", ask_user)
    builder.add_node("research", research)
    builder.add_node("plan", plan)
    builder.add_node("replan", replan)
    builder.add_node("budget_check", budget_check)
    builder.add_node("plan_approval", plan_approval)

    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage", route_after_triage,
        {"ask_user": "ask_user", "research": "research"},
    )
    builder.add_edge("ask_user", END)

    builder.add_edge("research", "plan")
    builder.add_edge("plan", "budget_check")
    builder.add_edge("replan", "budget_check")

    # budget_check → plan_approval, когда бюджет в порядке или попытки исчерпаны.
    builder.add_conditional_edges(
        "budget_check", route_after_budget,
        {"end": "plan_approval", "replan": "replan"},
    )
    builder.add_conditional_edges(
        "plan_approval", route_after_plan_approval,
        {"end": END, "replan": "replan"},
    )

    return builder.compile(checkpointer=checkpointer or InMemorySaver())