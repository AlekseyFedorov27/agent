from app.nodes.budget_check import budget_check, route_after_budget


def _state(*, budget=100.0, costs=None, costs_valid=True, costs_currency="EUR"):
    return {
        "request": {"budget": budget, "currency": "EUR"},
        "plan": {
            "markdown": "# Route\n\n<!-- BUDGET -->\n\n## Day 1",
            "costs": costs or {
                "hotels": 40.0,
                "activities": 20.0,
                "transport": 10.0,
                "food": 20.0,
            },
            "costs_valid": costs_valid,
            "costs_currency": costs_currency,
        },
        "replan_count": 0,
        "max_replans": 2,
    }


def test_budget_is_calculated_deterministically():
    result = budget_check(_state())
    report = result["budget_report"]

    assert report["status"] == "verified"
    assert report["total"] == 90.0
    assert report["fits"] is True
    assert "в пределах бюджета" in result["final_itinerary"]
    assert route_after_budget({"budget_report": report}) == "end"


def test_failed_cost_extraction_never_becomes_zero_and_fits():
    state = _state(costs={"hotels": 0, "activities": 0, "transport": 0, "food": 0}, costs_valid=False)
    result = budget_check(state)
    report = result["budget_report"]

    assert report["status"] == "unverified"
    assert report["fits"] is None
    assert report["total"] is None
    assert "Не удалось надёжно проверить" in result["final_itinerary"]
    assert route_after_budget({"budget_report": report}) == "end"


def test_currency_mismatch_is_not_compared_to_budget():
    result = budget_check(_state(costs_currency="USD"))
    report = result["budget_report"]

    assert report["status"] == "unverified"
    assert report["fits"] is None
    assert "Валюта расходов" in report["error"]


def test_over_budget_enters_replan_until_limit():
    state = _state(
        budget=50,
        costs={"hotels": 40, "activities": 20, "transport": 10, "food": 20},
    )
    result = budget_check(state)

    assert result["budget_report"]["status"] == "over_budget"
    assert "final_itinerary" not in result
    assert route_after_budget({"budget_report": result["budget_report"], "replan_count": 0, "max_replans": 2}) == "replan"


def test_missing_budget_skips_comparison():
    result = budget_check(_state(budget=None))

    assert result["budget_report"]["status"] == "no_budget"
    assert result["budget_report"]["fits"] is None
    assert "<!-- BUDGET -->" not in result["final_itinerary"]
