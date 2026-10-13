"""Детерминированная проверка бюджета и безопасная маршрутизация."""

import math
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.state import AgentState

COST_KEYS = ("hotels", "activities", "transport", "food")
LABELS = {
    "hotels": "Жильё",
    "activities": "Активности",
    "transport": "Транспорт",
    "food": "Питание",
}


def _render_budget_table(report: dict[str, Any]) -> str:
    """Формирует таблицу только для проверенного отчёта."""
    if report.get("status") == "no_budget":
        return ""
    if report.get("status") == "unverified":
        return (
            "## Проверка бюджета\n\n"
            "⚠️ Не удалось надёжно проверить стоимость маршрута. "
            "Не считайте этот план подтверждённым по бюджету. "
            f"Причина: {report.get('error') or 'неизвестная ошибка'}"
        )

    currency = report["currency"]
    breakdown = report["breakdown"]
    lines = [
        "## Бюджет", "", "| Статья | Стоимость |", "|---|---:|",
    ]
    for key in COST_KEYS:
        lines.append(f"| {LABELS[key]} | {breakdown[key]:.2f} {currency} |")
    lines.extend([
        f"| **Итого** | **{report['total']:.2f} {currency}** |",
        "",
    ])
    if report["fits"]:
        lines.append(f"Лимит: {report['limit']:.2f} {currency} — ✓ в пределах бюджета.")
    else:
        lines.append(
            f"Лимит: {report['limit']:.2f} {currency} — превышение "
            f"{report['over_by']:.2f} {currency}."
        )
    return "\n".join(lines)



def _with_budget_section(markdown: str, report: dict[str, Any]) -> str:
    """Вставляет отчёт в маркер или добавляет в конец, если маркер потерян."""
    section = _render_budget_table(report)
    if "<!-- BUDGET -->" in markdown:
        return markdown.replace("<!-- BUDGET -->", section)
    return f"{markdown.rstrip()}\n\n{section}" if section else markdown


def _valid_costs(costs: dict[str, Any]) -> dict[str, float] | None:
    normalized: dict[str, float] = {}
    try:
        for key in COST_KEYS:
            value = float(costs[key])
            if not math.isfinite(value) or value < 0:
                return None
            normalized[key] = value
    except (KeyError, TypeError, ValueError):
        return None
    return normalized


def budget_check(state: AgentState) -> dict[str, Any]:
    """Считает сумму только если данные прошли извлечение и валютную проверку."""
    plan = state.get("plan") or {}
    request = state.get("request") or {}
    markdown = str(plan.get("markdown") or "")
    currency = request.get("currency") or "EUR"
    raw_limit = request.get("budget")

    if raw_limit is None:
        report: dict[str, Any] = {
            "status": "no_budget", "total": None, "limit": None,
            "fits": None, "over_by": None, "currency": currency,
            "breakdown": {},
        }
        final_md = markdown.replace("<!-- BUDGET -->", "").rstrip()
        return {
            "budget_report": report,
            "final_itinerary": final_md,
            "messages": [AIMessage(content=final_md)],
        }

    try:
        limit = float(raw_limit)
        if not math.isfinite(limit) or limit < 0:
            raise ValueError
    except (TypeError, ValueError):
        limit = None

    costs = _valid_costs(plan.get("costs") or {})
    costs_valid = plan.get("costs_valid") is True
    costs_currency = plan.get("costs_currency")
    error = plan.get("costs_error")
    if limit is None:
        error = "Указан некорректный бюджет."
    elif not costs_valid:
        error = error or "Стоимость маршрута не прошла проверку."
    elif costs is None:
        error = "В данных о стоимости отсутствуют обязательные категории расходов."
    elif costs_currency != currency:
        error = f"Валюта расходов ({costs_currency or 'неизвестна'}) не совпадает с валютой бюджета ({currency})."

    if error:
        report = {
            "status": "unverified", "total": None, "limit": limit,
            "fits": None, "over_by": None, "currency": currency,
            "breakdown": costs or {}, "error": error,
        }
        final_md = _with_budget_section(markdown, report)
        return {
            "budget_report": report,
            "final_itinerary": final_md,
            "messages": [AIMessage(content=final_md)],
        }

    assert costs is not None and limit is not None
    total = sum(costs.values())
    fits = total <= limit
    over_by = max(0.0, total - limit)
    report = {
        "status": "verified" if fits else "over_budget",
        "total": total,
        "limit": limit,
        "fits": fits,
        "over_by": over_by,
        "currency": currency,
        "breakdown": costs,
    }

    replan_count = state.get("replan_count", 0)
    max_replans = state.get("max_replans", 2)
    is_final = fits or replan_count >= max_replans
    result: dict[str, Any] = {"budget_report": report}
    if is_final:
        final_md = _with_budget_section(markdown, report)
        result.update({
            "final_itinerary": final_md,
            "messages": [AIMessage(content=final_md)],
        })
    return result


def route_after_budget(state: AgentState) -> str:
    """Повторять план только при проверенном превышении бюджета."""
    report = state.get("budget_report") or {}
    if report.get("status") != "over_budget":
        return "end"
    if state.get("replan_count", 0) >= state.get("max_replans", 2):
        return "end"
    return "replan"
