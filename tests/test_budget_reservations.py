from concurrent.futures import ThreadPoolExecutor

import pytest
from types import SimpleNamespace

from app.economics.reservations import SQLBudgetReservations

class FakeLedger:
    def spend_today(self, app):
        return 0.0

def test_atomic_reservations_do_not_oversubscribe_shared_daily_limit(tmp_path):
    db = f"sqlite:///{tmp_path / 'budgets.db'}"
    reservations = SQLBudgetReservations(db, FakeLedger())
    def attempt(i):
        return reservations.reserve("demo-app", f"request-{i}", 0.001, 0.010)
    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(attempt, range(30)))
    assert sum(outcomes) == 10
    status = reservations.status("demo-app")
    assert abs(status["reserved_usd"] - 0.010) < 1e-9

def test_settlement_releases_reservation_and_tracks_actual_spend(tmp_path):
    reservations = SQLBudgetReservations(f"sqlite:///{tmp_path / 'budgets.db'}", FakeLedger())
    assert reservations.reserve("app", "r1", 0.004, 0.01)
    assert reservations.settle("r1", 0.003)
    status = reservations.status("app")
    assert status["reserved_usd"] == 0
    assert status["spent_usd"] == 0.003

def test_released_reservation_does_not_charge_spend(tmp_path):
    reservations = SQLBudgetReservations(f"sqlite:///{tmp_path / 'budgets.db'}", FakeLedger())
    assert reservations.reserve("app", "r1", 0.004, 0.01)
    assert reservations.release("r1")
    status = reservations.status("app")
    assert status["reserved_usd"] == 0
    assert status["spent_usd"] == 0

def test_expired_reservation_is_reclaimed(tmp_path):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session
    from app.economics.reservations import BudgetReservationRow
    reservations = SQLBudgetReservations(f"sqlite:///{tmp_path / 'budgets.db'}", FakeLedger())
    assert reservations.reserve("app", "r1", 0.004, 0.01)
    with Session(reservations.engine) as db, db.begin():
        row = db.get(BudgetReservationRow, "r1")
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    status = reservations.status("app")
    assert status["reserved_usd"] == 0
    assert reservations.reserve("app", "r2", 0.01, 0.01)


def test_reservations_are_shared_across_independent_worker_instances(tmp_path):
    db = f"sqlite:///{tmp_path / 'shared-workers.db'}"
    workers = [SQLBudgetReservations(db, FakeLedger()) for _ in range(4)]
    def attempt(i):
        return workers[i % len(workers)].reserve("shared-app", f"worker-request-{i}", 0.002, 0.020)
    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(attempt, range(40)))
    assert sum(outcomes) == 10
    status = workers[0].status("shared-app")
    assert abs(status["reserved_usd"] - 0.020) < 1e-9

def test_duplicate_request_id_is_idempotent_under_concurrency(tmp_path):
    db = f"sqlite:///{tmp_path / 'idempotent.db'}"
    workers = [SQLBudgetReservations(db, FakeLedger()) for _ in range(3)]
    def attempt(i):
        return workers[i % len(workers)].reserve("app", "same-request-id", 0.004, 0.01)
    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(attempt, range(24)))
    assert sum(outcomes) == 1
    assert abs(workers[0].status("app")["reserved_usd"] - 0.004) < 1e-9


def test_reservation_is_settled_after_a_graph_request(monkeypatch, tmp_path):
    """Regression: budget_reservation_id must survive in graph state (LangGraph drops undeclared
    keys), otherwise the execute node never settles it and the reservation leaks until lease expiry."""
    from app.gateway.state import GatewayState
    from tests.test_budgets import harness
    assert "budget_reservation_id" in GatewayState.__annotations__
    h = harness(monkeypatch, tmp_path, limit=0.01)
    result = h.ask("hello", session="settle-1")
    assert result["decision"] == "ALLOW"
    from app.economics.budget import BudgetService
    status = BudgetService(h.settings, h.policies, h.ledger).status("demo-app")
    assert status["reserved_usd"] == 0.0            # reservation released on settle
    assert status["spent_today_usd"] == pytest.approx(result["cost_usd"])
