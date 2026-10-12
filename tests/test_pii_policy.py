"""An application whose policy says allow_pii=false must be blocked when the
prompt contains PII. The flag used to be defined, loaded and never read."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.governance.engine import GovernanceEngine
from app.main import app
from app.policy.store import PolicyStore

client = TestClient(app)


def chat(application_id, prompt):
    return client.post("/v1/chat", json={"session_id": "pii-" + application_id, "application_id": application_id,
                                         "user_id": "u1", "prompt": prompt}).json()


def test_engine_blocks_pii_when_policy_forbids_it(tmp_path):
    settings = Settings()
    engine = GovernanceEngine(settings, PolicyStore("config/policies.json", settings))
    blocked = engine.evaluate("sre-agent", "mock-general", "hello", 1, True, {"developer", "operator", "admin"}, has_pii=True)
    assert not blocked.allowed and blocked.reason == "PII_NOT_ALLOWED"


def test_engine_still_allows_pii_when_policy_permits_it():
    settings = Settings()
    engine = GovernanceEngine(settings, PolicyStore("config/policies.json", settings))
    assert engine.evaluate("demo-app", "mock-general", "hello", 1, True, {"developer", "admin"}, has_pii=True).allowed


def test_default_is_unchanged_without_pii():
    settings = Settings()
    engine = GovernanceEngine(settings, PolicyStore("config/policies.json", settings))
    assert engine.evaluate("sre-agent", "mock-general", "hello", 1, True, {"developer", "operator", "admin"}).allowed


def test_end_to_end_pii_blocked_for_sre_agent_but_not_demo_app():
    prompt = "Customer email is jane@example.com, please check their incident."
    sre = chat("sre-agent", prompt)
    assert sre["governance"]["decision"] == "BLOCK" and sre["governance"]["reason"] == "PII_NOT_ALLOWED"
    assert chat("demo-app", prompt)["governance"]["decision"] == "ALLOW"
