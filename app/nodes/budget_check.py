"""Проверка бюджета без подмены оценок подтверждёнными ценами.

Статусы отчёта:
- no_budget: пользователь не задал лимит;
- unverified: недостаточно данных или ошибка валюты;
- verified: все расходы точные и сумма не превышает лимит;
- over_budget: все расходы точные и сумма превышает лимит;
- estimated: сумма ориентировочная или неполная (не подтверждена).

Автоматический replan разрешён только при точном превышении (over_budget).
"""

from typing import Any

from app.agent.state import AgentState

COST_KEYS = ("hotels", "activities", "transport", "food")
LABELS = {
    "hotels": "Жильё",
    "activities": "Активности",
    "transport": "Транспорт",
    "food": "Питание",
}
BUDGET_MARKER = "<!-- BUDGET -->"


def _money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", " ")


def _build_report(plan: dict[str, Any], limit: float | None, currency: str) -> dict[str, Any]:
    confidence = plan.get("costs_confidence") or "unknown"
    costs = plan.get("costs") or {}
    report: dict[str, Any] = {
        "status": "no_budget",
        "currency": currency,
        "limit": limit,
        "total": None,
        "over_by": None,
        "fits": None,
        "breakdown": costs,
        "confidence": confidence,
        "notes": plan.get("costs_notes") or "",
    }
    if limit is None:
        return report

    costs_currency = plan.get("costs_currency")
    error = None
    if costs_currency == "MIXED":
        error = "В плане смешаны несколько валют; без курса сумму нельзя сложить."
    elif costs_currency != currency:
        error = (
            f"Валюта плана ({costs_currency}) не совпадает с валютой бюджета ({currency}). "
            "Система не пересчитывает валюты без надёжного курса."
        )
    elif confidence == "unknown" or not all(k in costs for k in COST_KEYS):
        error = "Не удалось надёжно оценить стоимость маршрута."
    if error:
        return {**report, "status": "unverified", "error": error}

    total = sum(costs[k] for k in COST_KEYS)
    report["total"] = total
    if confidence == "exact":
        report.update(
            status="verified" if total <= limit else "over_budget",
            fits=total <= limit,
            over_by=max(0.0, total - limit),
        )
    else:
        report["status"] = "estimated"  # estimated и partial — не подтверждено
    return report


def _render(report: dict[str, Any]) -> str:
    status, cur = report["status"], report["currency"]
    if status == "no_budget":
        return ""
    if status == "unverified":
        return (
            "## Проверка бюджета\n\n"
            "⚠️ Бюджет не проверен, не считайте план подтверждённым.\n\n"
            f"Причина: {report.get('error')}"
        )

    rows = "\n".join(
        f"| {LABELS[k]} | {_money(report['breakdown'][k], cur)} |" for k in COST_KEYS
    )
    limit = _money(report["limit"], cur)
    verdict = {
        "verified": f"Лимит: {limit} — подтверждённая сумма в пределах бюджета.",
        "over_budget": (
            f"Лимит: {limit} — подтверждённое превышение "
            f"на {_money(report['over_by'], cur)}."
        ),
        "estimated": (
            f"Лимит: {limit}. Это ориентировочная оценка, а не подтверждённая цена; "
            "часть расходов может быть не учтена. Уточните цены перед бронированием."
        ),
    }[status]
    notes = f"\n\n**Допущения:** {report['notes']}" if report["notes"] else ""
    title = "## Оценка бюджета" if status == "estimated" else "## Бюджет"
    return (
        f"{title}\n\n| Статья | Стоимость |\n|---|---:|\n{rows}\n"
        f"| **Итого** | **{_money(report['total'], cur)}** |\n\n{verdict}{notes}"
    )


def budget_check(state: AgentState) -> dict[str, Any]:
    plan = state.get("plan") or {}
    request = state.get("request") or {}
    report = _build_report(plan, request.get("budget"), request.get("currency") or "EUR")

    markdown = str(plan.get("markdown") or "")
    section = _render(report)
    if BUDGET_MARKER in markdown:
        final_md = markdown.replace(BUDGET_MARKER, section)
    else:
        final_md = f"{markdown.rstrip()}\n\n{section}"
    return {"budget_report": report, "final_itinerary": final_md.rstrip()}


def route_after_budget(state: AgentState) -> str:
    """Автоматический replan только при подтверждённом превышении бюджета."""
    over = (state.get("budget_report") or {}).get("status") == "over_budget"
    can_replan = state.get("replan_count", 0) < state.get("max_replans", 2)
    return "replan" if over and can_replan else "end"