"""Проверка бюджета без подмены оценок подтверждёнными ценами.

Статусы отчёта:
- no_budget: пользователь не задал лимит;
- unverified: недостаточно данных, ошибка валюты или некорректные значения;
- verified: все расходы точные и сумма не превышает лимит;
- over_budget: все расходы точные и сумма превышает лимит;
- estimated: сумма ориентировочная (все категории оценены);
- partial: сумма неполная или смешивает подтверждённые и оценочные данные.

Автоматическое перепланирование разрешено только при точном превышении
(over_budget). Оценка выше лимита — предупреждение для пользователя, а не факт.
"""

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
BUDGET_MARKER = "<!-- BUDGET -->"


def _valid_costs(costs: Any) -> dict[str, float] | None:
    """Проверяет наличие всех обязательных категорий и нормализует суммы."""
    if not isinstance(costs, dict):
        return None
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


def _valid_limit(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", " ")


def _render_budget_table(report: dict[str, Any]) -> str:
    """Рендерит отчёт, не называя ориентировочную сумму проверенной."""
    status = report.get("status")
    if status == "no_budget":
        return ""
    if status == "unverified":
        return (
            "## Проверка бюджета\n\n"
            "⚠️ Не удалось надёжно проверить стоимость маршрута. "
            "Не считайте этот план подтверждённым по бюджету.\n\n"
            f"Причина: {report.get('error') or 'недостаточно данных'}"
        )

    currency = str(report.get("currency") or "EUR")
    breakdown = report.get("breakdown") or {}
    lines = [
        "## Оценка бюджета" if status in {"estimated", "partial"} else "## Бюджет",
        "",
        "| Статья | Стоимость |",
        "|---|---:|",
    ]
    for key in COST_KEYS:
        lines.append(f"| {LABELS[key]} | {_money(float(breakdown[key]), currency)} |")
    lines.extend([
        f"| **Итого** | **{_money(float(report['total']), currency)}** |",
        "",
    ])

    limit = float(report["limit"])
    confidence = report.get("confidence")
    if status == "verified":
        lines.append(f"Лимит: {_money(limit, currency)} — подтверждённая сумма в пределах бюджета.")
    elif status == "over_budget":
        lines.append(
            f"Лимит: {_money(limit, currency)} — подтверждённое превышение "
            f"на {_money(float(report['over_by']), currency)}."
        )
    elif status == "estimated":
        lines.append(
            f"Лимит: {_money(limit, currency)}. Это ориентировочная оценка, "
            "а не подтверждённая цена; соответствие бюджету не гарантировано."
        )
    elif status == "partial":
        lines.append(
            f"Лимит: {_money(limit, currency)}. Оценка неполная; часть расходов "
            "может быть не учтена. Нельзя подтвердить, что поездка уложится в бюджет."
        )

    notes = report.get("notes")
    if notes:
        lines.extend(["", f"**Допущения:** {notes}"])
    if confidence in {"estimated", "partial"}:
        lines.extend(["", "Перед бронированием уточните цены и доступность у поставщиков."])
    return "\n".join(lines)


def _with_budget_section(markdown: str, report: dict[str, Any]) -> str:
    section = _render_budget_table(report)
    if BUDGET_MARKER in markdown:
        return markdown.replace(BUDGET_MARKER, section)
    if not section:
        return markdown
    return f"{markdown.rstrip()}\n\n{section}"


def budget_check(state: AgentState) -> dict[str, Any]:
    """Формирует отчёт. Не делает выводов о бюджете на основании оценок."""
    plan = state.get("plan") or {}
    request = state.get("request") or {}
    markdown = str(plan.get("markdown") or "")
    currency = str(request.get("currency") or "EUR")
    raw_limit = request.get("budget")
    confidence = str(plan.get("costs_confidence") or "unknown")
    allowed_confidence = {"exact", "estimated", "partial", "unknown"}
    if confidence not in allowed_confidence:
        confidence = "unknown"

    if raw_limit is None:
        report = {
            "status": "no_budget", "total": None, "limit": None,
            "fits": None, "over_by": None, "currency": currency,
            "confidence": confidence, "breakdown": {},
        }
        final_md = markdown.replace(BUDGET_MARKER, "").rstrip()
        return {"budget_report": report, "final_itinerary": final_md,
                "messages": [AIMessage(content=final_md)]}

    limit = _valid_limit(raw_limit)
    costs = _valid_costs(plan.get("costs"))
    costs_valid = plan.get("costs_valid") is True
    costs_currency = plan.get("costs_currency")
    error = plan.get("costs_error")

    if limit is None:
        error = "Указан некорректный бюджет."
    elif costs is None:
        error = "В данных о стоимости отсутствуют обязательные категории расходов."
    elif costs_currency == "MIXED":
        error = "В плане смешаны несколько валют; без надёжного курса сумму нельзя сложить."
    elif costs_currency not in (None, currency):
        error = (
            f"Валюта расходов ({costs_currency}) не совпадает с валютой бюджета ({currency}). "
            "Система не пересчитывает валюты без надёжного курса."
        )
    elif not costs_valid:
        error = error or "Стоимость маршрута не прошла проверку."
    elif confidence == "unknown":
        error = "Точность оценки неизвестна; сравнение с бюджетом ненадёжно."

    if error:
        report = {
            "status": "unverified", "total": None, "limit": limit,
            "fits": None, "over_by": None, "currency": currency,
            "confidence": confidence, "breakdown": costs or {}, "error": error,
        }
        final_md = _with_budget_section(markdown, report)
        return {"budget_report": report, "final_itinerary": final_md,
                "messages": [AIMessage(content=final_md)]}

    assert costs is not None and limit is not None
    total = sum(costs.values())
    over_by = max(0.0, total - limit)

    # Только точные суммы позволяют выдать однозначный вердикт.
    if confidence == "exact":
        status = "verified" if total <= limit else "over_budget"
        fits: bool | None = total <= limit
        reported_over_by: float | None = over_by
    elif confidence == "estimated":
        status, fits, reported_over_by = "estimated", None, None
    else:  # partial
        status, fits, reported_over_by = "partial", None, None

    report = {
        "status": status,
        "total": total,
        "limit": limit,
        "fits": fits,
        "over_by": reported_over_by,
        "currency": currency,
        "confidence": confidence,
        "breakdown": costs,
        "notes": plan.get("costs_notes") or "",
    }
    result: dict[str, Any] = {"budget_report": report}

    # Оценочные суммы всегда доходят до пользователя сразу: не запускаем
    # автоматические циклы, основанные на предположительных цифрах.
    if status != "over_budget" or state.get("replan_count", 0) >= state.get("max_replans", 2):
        final_md = _with_budget_section(markdown, report)
        result["final_itinerary"] = final_md
        result["messages"] = [AIMessage(content=final_md)]
    return result


def route_after_budget(state: AgentState) -> str:
    """Автоматический replan только при подтверждённом превышении бюджета."""
    report = state.get("budget_report") or {}
    if report.get("status") != "over_budget":
        return "end"
    if state.get("replan_count", 0) >= state.get("max_replans", 2):
        return "end"
    return "replan"
