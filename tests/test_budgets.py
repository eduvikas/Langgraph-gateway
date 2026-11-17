"""Per-application daily budgets: blocked before the model is called, shared via the ledger."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.economics.budget import BudgetService
from app.main import app
from tests.economics_helpers import Harness, make_settings

ROW = dict(request_id="r", user_id="u", session_id="s", provider="openai", model="gpt-5.6-luna", decision="ALLOW", status="success")


def policies(tmp_path, **apps):
    path = tmp_path / "policies.json"
    path.write_text(json.dumps({"applications": apps}), encoding="utf-8")
    return str(path)


def harness(monkeypatch, tmp_path, limit=0.002, other=None, **kw):
    apps = {"demo-app": ({"daily_budget_usd": limit} if limit is not None else {}), "contract-agent": other or {"daily_budget_usd": limit}}
    return Harness(monkeypatch, tmp_path, budgeted=True, policy_file=policies(tmp_path, **apps), **kw)


def test_requests_pass_until_the_budget_is_reached_then_block_without_calling_the_model(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=0.002)             # each call costs 0.0008; estimate before a call is ~0.0006
    results = [h.ask(f"q{i}", session=f"s{i}") for i in range(3)]
    assert [r["decision"] for r in results] == ["ALLOW", "ALLOW", "BLOCK"]
    assert results[2]["block_reason"] == "BUDGET_EXCEEDED"
    assert len(h.calls) == 2                                      # the third request never reached the provider
    assert results[2]["budget"]["spent_today_usd"] == pytest.approx(0.0016)
    blocked_row = h.ledger.recent(1)[0]
    assert blocked_row["decision"] == "BLOCK" and blocked_row["cost_usd"] == 0.0 and blocked_row["total_tokens"] == 0


def test_budgets_are_per_application(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=0.002)
    for i in range(3): h.ask(f"q{i}", app="demo-app", session=f"d{i}")
    assert h.ask("hello", app="contract-agent", session="o1")["decision"] == "ALLOW"   # its own budget is untouched


def test_alert_flag_when_utilisation_passes_the_threshold(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=0.002)
    assert h.ask("a", session="a")["budget"]["alert"] is False
    h.ask("b", session="b")
    status = BudgetService(h.settings, h.policies, h.ledger).status("demo-app")
    assert status["utilization"] == pytest.approx(0.8) and status["alert"] is True and status["remaining_usd"] == pytest.approx(0.0004)


def test_yesterdays_spend_does_not_count(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=0.01)
    h.ledger.record(application_id="demo-app", cost_usd=100.0, created_at=datetime.now(timezone.utc) - timedelta(days=1, hours=1), **ROW)
    assert h.ask()["decision"] == "ALLOW"


def test_no_limit_means_unlimited(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=None, other={})
    h.ledger.record(application_id="demo-app", cost_usd=10_000.0, **ROW)
    r = h.ask()
    assert r["decision"] == "ALLOW" and r["budget"]["unlimited"] is True


def test_default_budget_applies_when_the_policy_sets_none(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=None, other={}, settings=make_settings(default_daily_budget_usd=0.001))
    assert h.ask("a", session="a")["decision"] == "ALLOW"        # 0 spent + ~0.0006 estimate <= 0.001
    assert h.ask("b", session="b")["decision"] == "BLOCK"        # 0.0008 spent + ~0.0006 > 0.001


def test_policy_zero_means_unlimited_even_with_a_default(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path, limit=0, other={"daily_budget_usd": 0}, settings=make_settings(default_daily_budget_usd=0.0001))
    assert all(h.ask(f"q{i}", session=f"s{i}")["decision"] == "ALLOW" for i in range(3))


def test_cost_estimate_uses_prompt_history_and_an_assumed_answer(monkeypatch, tmp_path):
    h = harness(monkeypatch, tmp_path)
    svc = BudgetService(make_settings(budget_output_estimate_tokens=500), h.policies, h.ledger)
    # 400 chars of prompt + 400 of history = 200 input tokens; 500 assumed output tokens, on luna
    cost = svc.estimate_cost("openai", "gpt-5.6-luna", "x" * 400, [{"content": "y" * 400}])
    assert cost == pytest.approx(200 * 0.20 / 1e6 + 500 * 1.20 / 1e6)


def test_response_carries_the_budget_position():
    uid = uuid.uuid4().hex
    r = TestClient(app).post("/v1/chat", json={"session_id": "bud-" + uid, "application_id": "demo-app", "user_id": "u1", "prompt": "hello " + uid}).json()
    assert set(r["budget"]) >= {"limit_usd", "spent_today_usd", "remaining_usd", "utilization", "alert", "unlimited"}
    assert r["budget"]["limit_usd"] == 5.0        # the example budget in config/policies.json
