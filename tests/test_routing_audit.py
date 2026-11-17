import json
from sqlalchemy.orm import Session
from app.audit.store import AuditEvent, AuditStore


def test_routing_decision_is_persisted_and_returned_as_structured_data(tmp_path):
    store = AuditStore(f"sqlite:///{tmp_path / 'audit.db'}")
    decision = {
        "task_classification": "reasoning",
        "selected_model": "model-primary",
        "selected_provider": "openai",
        "ranked_alternatives": [
            {"provider": "openai", "model": "model-primary", "score": 0.93},
            {"provider": "openai", "model": "model-fallback", "score": 0.77},
        ],
        "routing_reason": "reasoning capability required",
        "estimated_cost_usd": 0.0123,
        "reservation_id": "br_abc123",
        "final_executed_model": "model-fallback",
        "final_executed_provider": "openai",
        "failed_models": ["model-primary"],
    }
    store.record(
        event_type="CHAT_COMPLETED", request_id="req-1", user_id="u1",
        application_id="app1", session_id="s1", outcome="ALLOW",
        classification="internal", routing_decision=decision,
    )

    recent = store.recent(1)[0]
    assert recent["routing_decision"] == decision
    with Session(store.engine) as db:
        row = db.query(AuditEvent).one()
        assert json.loads(row.routing_decision)["final_executed_model"] == "model-fallback"


def test_existing_audit_database_gets_routing_column_migration(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'legacy-audit.db'}"
    first = AuditStore(db_url)
    # Simulate a legacy schema by removing the new column, then reconstructing the store.
    from sqlalchemy import text, inspect
    with first.engine.begin() as connection:
        connection.execute(text("ALTER TABLE gateway_security_audit DROP COLUMN routing_decision"))
    assert "routing_decision" not in {c["name"] for c in inspect(first.engine).get_columns("gateway_security_audit")}

    migrated = AuditStore(db_url)
    assert "routing_decision" in {c["name"] for c in inspect(migrated.engine).get_columns("gateway_security_audit")}
