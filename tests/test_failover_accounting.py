"""Failover must be accounted for correctly: money is reserved, released and settled for the model that really ran,
and the usage ledger records that model rather than the one the router first chose."""
import pytest

from app.economics.pricing import PRICING, price_call
from tests.economics_helpers import Harness, make_settings
from tests.support import write_policy_file

TOKENS = (1000, 500)


def budgeted(monkeypatch, tmp_path, *, failing=(), limit=5.0, models=None, settings=None):
    settings = settings or make_settings()
    policy = write_policy_file(tmp_path, models, settings=settings, **{"demo-app": {"daily_budget_usd": limit}})
    return Harness(monkeypatch, tmp_path, tokens=TOKENS, settings=settings, policy_file=policy, budgeted=True, failing=failing)


def reservation_state(h, app="demo-app"):
    """The reservation tables themselves. BudgetService.status() reports max(reservation spend, ledger spend), and the
    harness writes true cost to the ledger, so status() alone would hide a wrong settlement. Read the source of truth."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.economics.reservations import BudgetReservationRow, DailyBudgetRow
    with Session(h.budget.reservations.engine) as db:
        daily = db.scalars(select(DailyBudgetRow).where(DailyBudgetRow.application_id == app)).one()
        rows = db.scalars(select(BudgetReservationRow).where(BudgetReservationRow.application_id == app)).all()
        return {"spent": daily.spent_usd, "reserved": daily.reserved_usd,
                "statuses": sorted(r.status for r in rows), "by_model": {r.request_id.rsplit(":", 1)[-1]: r.status for r in rows}}


def cost_of(h, model):
    return price_call(h.settings, "openai", model, *TOKENS).cost_usd


def test_spend_is_settled_for_the_model_that_answered_not_the_one_that_failed(monkeypatch, tmp_path):
    h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna"})
    r = h.ask()
    assert r["decision"] == "ALLOW" and r["selected_model"] == "gpt-5.6-terra" and r["failed_models"] == ["gpt-5.6-luna"]
    assert h.calls[:2] == ["gpt-5.6-luna", "gpt-5.6-terra"]
    state = reservation_state(h)
    assert state["reserved"] == pytest.approx(0.0, abs=1e-12)                # nothing left held for the failed attempt
    assert state["spent"] == pytest.approx(cost_of(h, "gpt-5.6-terra"))      # the actual cost, of the model that ran
    assert state["statuses"] == ["released", "settled"]                      # luna's hold released, terra's settled
    assert r["cost_usd"] == pytest.approx(cost_of(h, "gpt-5.6-terra"))


def test_ledger_records_the_model_that_ran(monkeypatch, tmp_path):
    h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna"})
    h.ask()
    assert h.ledger.spend_today("demo-app") == pytest.approx(cost_of(h, "gpt-5.6-terra"))
    by_model = {row["model"]: row for row in h.ledger.by_model()}
    assert set(by_model) == {"gpt-5.6-terra"}                                  # luna failed: no row, no tokens, no cost
    assert by_model["gpt-5.6-terra"]["cost_usd"] == pytest.approx(cost_of(h, "gpt-5.6-terra"))


def test_total_failure_releases_every_reservation(monkeypatch, tmp_path):
    h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"})
    with pytest.raises(RuntimeError, match="ALL_MODELS_FAILED"):
        h.ask()
    state = reservation_state(h)
    assert state["reserved"] == pytest.approx(0.0, abs=1e-12) and state["spent"] == 0.0
    assert state["statuses"] == ["released"] * 3 and "active" not in state["statuses"]


def test_repeated_failures_do_not_leak_reservations(monkeypatch, tmp_path):
    h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna"})
    for i in range(5):
        h.ask(prompt=f"question {i}", session=f"s{i}")
    state = reservation_state(h)
    assert state["reserved"] == pytest.approx(0.0, abs=1e-12) and "active" not in state["statuses"]
    assert state["spent"] == pytest.approx(5 * cost_of(h, "gpt-5.6-terra"))


def test_failover_candidate_that_would_bust_the_budget_is_skipped(monkeypatch, tmp_path):
    settings = make_settings()
    probe = budgeted(monkeypatch, tmp_path / "probe", settings=settings) if (tmp_path / "probe").mkdir() is None else None
    est = lambda m: probe.budget.estimate_cost("openai", m, "hello", [])       # the same preflight estimate the graph uses
    limit = (est("gpt-5.6-luna") + est("gpt-5.6-terra")) / 2                    # enough for luna only
    assert est("gpt-5.6-luna") < limit < est("gpt-5.6-terra")
    h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna"}, limit=limit)
    with pytest.raises(RuntimeError, match="ALL_MODELS_FAILED"):
        h.ask()
    assert h.calls == ["gpt-5.6-luna"]                                         # terra/sol were unaffordable, never called
    state = reservation_state(h)
    assert state["reserved"] == pytest.approx(0.0, abs=1e-12) and state["spent"] == 0.0 and "active" not in state["statuses"]


def test_failover_skips_an_unpriced_candidate_instead_of_inventing_a_price(monkeypatch, tmp_path):
    settings = make_settings(model_pricing_json="")
    saved = PRICING.pop("gpt-5.6-terra")
    try:
        h = budgeted(monkeypatch, tmp_path, failing={"gpt-5.6-luna"}, settings=settings)
        r = h.ask()
    finally:
        PRICING["gpt-5.6-terra"] = saved
    assert r["selected_model"] == "gpt-5.6-sol" and "gpt-5.6-terra:UNPRICED_MODEL" in r["failed_models"]
    assert "gpt-5.6-terra" not in h.calls
