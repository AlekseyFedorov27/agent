"""Типизированный контракт состояния LangGraph."""

from typing import Annotated, Any, Literal, TypedDict
from typing_extensions import NotRequired

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

Currency = Literal["EUR", "USD", "RUB"]
CostCategory = Literal["hotels", "activities", "transport", "food"]


class Request(TypedDict, total=False):
    currency: Currency
    destination: str | None
    country: str | None
    duration_days: int | None
    month: str | None
    budget: float | None
    interests: list[str]
    travel_type: Literal["solo", "family", "couple", "business"] | None
    constraints: list[str]


class ResearchDocument(TypedDict, total=False):
    doc_id: str
    content: str
    meta: dict[str, Any]
    score: float


class Research(TypedDict):
    attractions: list[ResearchDocument]
    restaurants: list[ResearchDocument]
    rules: list[ResearchDocument]


class Plan(TypedDict):
    markdown: str
    costs: dict[str, float]
    # None = cost extraction wasn't required (no budget supplied).
    costs_valid: bool | None
    costs_error: NotRequired[str | None]
    costs_currency: NotRequired[str | None]


class BudgetReport(TypedDict):
    status: Literal["no_budget", "verified", "over_budget", "unverified"]
    total: float | None
    limit: float | None
    fits: bool | None
    over_by: float | None
    currency: Currency
    breakdown: dict[str, float]
    error: NotRequired[str | None]


class QualityReport(TypedDict):
    passed: bool
    issues: list[str]


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_name: str
    system_prompt: str
    approval_decision: Literal["approved", "rejected"] | None

    request: Request
    missing_fields: list[str]
    question_to_user: str | None

    research: Research
    plan: Plan | None
    budget_report: BudgetReport | None
    quality_report: QualityReport | None
    final_itinerary: str | None
    triage_error: str | None

    replan_count: int
    max_replans: int
