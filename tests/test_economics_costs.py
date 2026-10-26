"""Cost accounting: pricing arithmetic, the savings baseline, ledger aggregates and migration."""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.control_tower.metrics import ControlTower
from app.economics.pricing import cost_usd, price_call
from app.main import app
from app.usage.ledger import UsageLedger
from tests.economics_helpers import Harness, make_settings


def test_cost_arithmetic_per_million_tokens():
    assert cost_usd("gpt-5.6-sol", 1_000_000, 1_000_000) == 24.0
    assert cost_usd("gpt-5.6-terra", 1_000_000, 1_000_000) == 14.0
    assert cost_usd("gpt-5.6-luna", 1_000_000, 1_000_000) == 1.4
    assert cost_usd("gpt-5.6-luna", 1000, 500) == 0.0008
    assert cost_usd("not-a-model", 1000, 500) == 0


def test_real_model_is_priced_against_the_baseline():
    c = price_call(Settings(), "openai", "gpt-5.6-luna", 1000, 500)
    assert (c.cost_usd, c.baseline_cost_usd, c.billable, c.priced) == (0.0008, 0.014, True, True)


def test_mock_provider_is_not_billed_so_it_cannot_fake_a_saving():
    c = price_call(Settings(), "mock", "mock-general", 1000, 500)
    assert (c.cost_usd, c.baseline_cost_usd, c.billable) == (0.0, 0.0, False)


def test_mock_can_be_priced_as_a_real_model_for_demos():
    c = price_call(Settings(mock_pricing_model="gpt-5.6-luna"), "mock", "mock-general", 1000, 500)
    assert (c.cost_usd, c.baseline_cost_usd, c.billable) == (0.0008, 0.014, True)


def test_unknown_real_model_is_flagged_not_silently_free():
    c = price_call(Settings(), "openai", "gpt-mystery", 1000, 500)
    assert c.priced is False and c.billable is True
    assert c.cost_usd == 0 and c.baseline_cost_usd == 0  # no invented savings without a known price


def test_unpriced_economics_response_does_not_claim_savings():
    from app.economics.accounting import economics_block
    result = economics_block({"cost_usd": 0.0, "baseline_cost_usd": 0.0, "priced": False})
    assert result["priced"] is False
    assert result["cost_usd"] is None and result["baseline_cost_usd"] is None
    assert result["savings_usd"] is None


def test_pipeline_prices_each_call_and_records_the_baseline(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, tokens=(1000, 500))
    result = h.ask()
    assert result["selected_model"] == "gpt-5.6-luna"
    assert (result["cost_usd"], result["baseline_cost_usd"]) == (0.0008, 0.014)
    row = h.ledger.recent(1)[0]
    assert (row["cost_usd"], row["baseline_cost_usd"], row["total_tokens"]) == (0.0008, 0.014, 1500)


def test_baseline_model_is_configurable(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, settings=make_settings(baseline_model="gpt-5.6-terra"))
    r = h.ask()
    assert r["baseline_cost_usd"] == cost_usd("gpt-5.6-terra", 1000, 500)


def test_economics_summary_adds_up(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path)
    for i in range(3): h.ask(f"question {i}", session=f"s{i}")
    e = ControlTower(h.ledger, None, None).economics(days=1)["totals"]
    assert e["requests"] == 3 and e["tokens"] == 4500
    assert e["cost_usd"] == pytest.approx(0.0024) and e["baseline_cost_usd"] == pytest.approx(0.042)
    assert e["savings_usd"] == pytest.approx(0.0396) and e["savings_pct"] == pytest.approx(0.9429, abs=1e-4)


def test_mock_traffic_shows_no_savings(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, settings=make_settings(openai_api_key="", mock_provider_enabled=True))
    r = h.ask()
    assert r["selected_provider"] == "mock" and r["billable"] is False
    e = ControlTower(h.ledger, None, None).economics()["totals"]
    assert e["cost_usd"] == 0 and e["baseline_cost_usd"] == 0 and e["savings_usd"] == 0


def test_spend_today_is_per_application_and_per_day(tmp_path):
    ledger = UsageLedger(f"sqlite:///{tmp_path / 'u.db'}")
    now = datetime.now(timezone.utc)
    row = dict(request_id="r", user_id="u", session_id="s", provider="openai", model="gpt-5.6-luna", decision="ALLOW", status="success")
    ledger.record(application_id="a", cost_usd=1.5, **row)
    ledger.record(application_id="a", cost_usd=0.25, **row)
    ledger.record(application_id="b", cost_usd=9.0, **row)
    ledger.record(application_id="a", cost_usd=100.0, created_at=now - timedelta(days=1, hours=1), **row)   # yesterday
    assert ledger.spend_today("a") == 1.75 and ledger.spend_today("b") == 9.0 and ledger.spend_today("nobody") == 0.0


def test_aggregates_are_not_capped_at_1000_events(tmp_path):
    ledger = UsageLedger(f"sqlite:///{tmp_path / 'u.db'}")
    for i in range(1500):
        ledger.record(request_id=str(i), user_id="u", application_id="a", session_id="s", provider="openai", model="m",
                      total_tokens=2, cost_usd=0.001, decision="ALLOW", status="success")
    t = ledger.totals()
    assert t["requests"] == 1500 and t["tokens"] == 3000 and t["cost_usd"] == pytest.approx(1.5)


def test_database_from_an_older_version_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE gateway_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id VARCHAR(100), user_id VARCHAR(100),
        application_id VARCHAR(100), session_id VARCHAR(200), provider VARCHAR(50), model VARCHAR(100), input_tokens INTEGER,
        output_tokens INTEGER, total_tokens INTEGER, decision VARCHAR(20), status VARCHAR(30), error TEXT, created_at DATETIME)""")
    con.execute("INSERT INTO gateway_usage (request_id,user_id,application_id,session_id,provider,model,input_tokens,output_tokens,"
                "total_tokens,decision,status,created_at) VALUES ('r','u','a','s','openai','gpt-5.6-sol',10,5,15,'ALLOW','success',?)",
                (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" "),))
    con.commit(); con.close()
    ledger = UsageLedger(f"sqlite:///{path}")                         # opening it adds the new columns
    old = ledger.recent(1)[0]
    assert old["total_tokens"] == 15 and old["cost_usd"] == 0.0 and old["cache_hit"] is False
    ledger.record(request_id="r2", user_id="u", application_id="a", session_id="s", provider="openai", model="m",
                  decision="ALLOW", status="success", cost_usd=0.5)
    assert ledger.totals()["requests"] == 2 and ledger.totals()["cost_usd"] == 0.5


def test_chat_response_carries_an_economics_block():
    uid = uuid.uuid4().hex
    r = TestClient(app).post("/v1/chat", json={"session_id": "econ-" + uid, "application_id": "demo-app", "user_id": "u1",
                                              "prompt": "hello " + uid}).json()
    assert set(r["economics"]) >= {"cost_usd", "baseline_cost_usd", "savings_usd", "cache_hit", "tokens_avoided", "billable"}
    assert r["cache_hit"] is False and r["estimated_cost_usd"] == r["economics"]["cost_usd"]
