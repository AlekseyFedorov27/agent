from app.nodes.budget_check import budget_check, route_after_budget


def make_state(*, confidence="exact", costs=None, currency="EUR", budget=800, **extra):
    plan = {
        "markdown": "# Маршрут\n\n<!-- BUDGET -->",
        "costs": costs or {"hotels": 300, "activities": 100, "transport": 100, "food": 200},
        "costs_valid": True,
        "costs_currency": currency,
        "costs_confidence": confidence,
        "costs_notes": "Тестовые допущения",
    }
    state = {"plan": plan, "request": {"budget": budget, "currency": "EUR"}, **extra}
    return state


def test_exact_cost_within_budget_is_verified():
    result = budget_check(make_state())
    assert result["budget_report"]["status"] == "verified"
    assert result["budget_report"]["fits"] is True
    assert "подтверждённая сумма в пределах бюджета" in result["final_itinerary"]


def test_estimated_cost_is_not_claimed_to_fit_budget():
    result = budget_check(make_state(confidence="estimated", budget=800))
    report = result["budget_report"]
    assert report["status"] == "estimated"
    assert report["fits"] is None
    assert report["over_by"] is None
    assert "соответствие бюджету не гарантировано" in result["final_itinerary"]
    assert route_after_budget({"budget_report": report}) == "end"


def test_partial_cost_is_not_claimed_to_fit_budget():
    result = budget_check(make_state(confidence="partial"))
    assert result["budget_report"]["status"] == "partial"
    assert result["budget_report"]["fits"] is None
    assert "оценка неполная" in result["final_itinerary"].lower()


def test_exact_over_budget_routes_to_replan():
    result = budget_check(make_state(budget=500))
    assert result["budget_report"]["status"] == "over_budget"
    assert result["budget_report"]["fits"] is False
    assert route_after_budget({"budget_report": result["budget_report"], "replan_count": 0, "max_replans": 2}) == "replan"


def test_currency_mismatch_is_unverified():
    result = budget_check(make_state(currency="USD"))
    assert result["budget_report"]["status"] == "unverified"
    assert result["budget_report"]["fits"] is None


def test_missing_cost_category_is_unverified():
    result = budget_check(make_state(costs={"hotels": 300, "activities": 100, "food": 200}))
    assert result["budget_report"]["status"] == "unverified"


def test_no_budget_does_not_show_budget_section():
    result = budget_check(make_state(budget=None))
    assert result["budget_report"]["status"] == "no_budget"
    assert "## Бюджет" not in result["final_itinerary"]


def test_partial_does_not_trigger_replan():
    result = budget_check(make_state(confidence="partial"))
    assert route_after_budget({
        "budget_report": result["budget_report"],
        "replan_count": 0, "max_replans": 2,
    }) == "end"

def test_unverified_does_not_trigger_replan():
    result = budget_check(make_state(currency="USD"))
    assert route_after_budget({
        "budget_report": result["budget_report"],
        "replan_count": 0, "max_replans": 2,
    }) == "end"