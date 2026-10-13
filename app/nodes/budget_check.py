from typing import Any

from langchain_core.messages import AIMessage

from app.agent.state import AgentState


def _render_budget_table(report: dict[str, Any]) -> str:
    """Готовит markdown-таблицу для вставки вместо <!-- BUDGET -->."""
    if not report.get("limit"):
        return ""  # бюджет не задан — не рисуем таблицу

    bd = report.get("breakdown") or {}
    cur = report.get("currency", "EUR")

    lines = [
        "## Бюджет",
        "",
        "| Статья | Стоимость |",
        "|---|---|",
        f"| Жильё | {bd.get('hotels_eur', 0):.0f} {cur} |",
        f"| Активности | {bd.get('activities_eur', 0):.0f} {cur} |",
        f"| Транспорт | {bd.get('transport_eur', 0):.0f} {cur} |",
        f"| Питание | {bd.get('food_eur', 0):.0f} {cur} |",
        f"| **Итого** | **{report['total']:.0f} {cur}** |",
        "",
    ]

    if report["fits"]:
        lines.append(f"Бюджет: {report['limit']:.0f} {cur} — ✓ Укладываемся.")
    else:
        lines.append(
            f"Бюджет: {report['limit']:.0f} {cur} — "
            f"⚠ Превышение на {report['over_by']:.0f} {cur}."
        )

    return "\n".join(lines)


def budget_check(state: AgentState) -> dict[str, Any]:
    """
    Детерминированный расчёт бюджета.
    Сравнивает сумму 4 статей с лимитом пользователя.
    """
    plan = state.get("plan") or {}
    costs = plan.get("costs") or {}
    markdown = plan.get("markdown", "")
    request = state.get("request") or {}

    total = sum(
        float(costs.get(k) or 0)
        for k in ("hotels_eur", "activities_eur", "transport_eur", "food_eur")
    )
    limit = float(request.get("budget") or 0)
    fits = (limit == 0) or (total <= limit)

    report = {
        "total": total,
        "limit": limit,
        "fits": fits,
        "over_by": max(0.0, total - limit),
        "breakdown": costs,
        "currency": request.get("currency", "EUR"),
    }

    result: dict[str, Any] = {"budget_report": report}

    # Финальный план попадает в messages только когда:
    #   1) он влезает, ИЛИ
    #   2) мы исчерпали попытки перепланирования
    replan_count = state.get("replan_count", 0)
    max_replans = state.get("max_replans", 2)
    is_final = fits or (replan_count >= max_replans)

    if is_final:
        final_md = markdown.replace("<!-- BUDGET -->", _render_budget_table(report))
        result["final_itinerary"] = final_md
        result["messages"] = [AIMessage(content=final_md)]

    return result


def route_after_budget(state: AgentState) -> str:
    """
    END, если план влез или попытки исчерпаны.
    Иначе — replan.
    """
    report = state.get("budget_report") or {}
    if report.get("fits"):
        return "end"
    if state.get("replan_count", 0) >= state.get("max_replans", 2):
        return "end"
    return "replan"