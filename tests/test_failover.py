"""Failover must report the model that actually answered, and must never land on
a model the application's policy does not allow."""
import json
from pathlib import Path

import pytest

import app.gateway.graph as graph_module
from app.config import Settings
from app.gateway.graph import build_gateway_graph
from app.governance.engine import GovernanceEngine
from app.policy.store import PolicyStore
from app.providers.base import ModelResponse

ROOT = Path(__file__).resolve().parent.parent


class FakeMemory:
    def increment_request_count(self, *a, **k): return 1
    def get_history(self, *a, **k): return []
    def append(self, *a, **k): return None


class FakeLimiter:
    def allow(self, key): return True, 59


class FakeAudit:
    def record(self, **k): return None


def make_graph(monkeypatch, failing, policy_file=None):
    settings = Settings(openai_api_key="sk-test-not-real", mock_provider_enabled=False, auth_enabled=False,
                        allowed_models_raw="gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna")

    class Provider:
        def generate(self, prompt, history, model, max_output_tokens):
            if model in failing:
                raise RuntimeError("simulated outage " + model)
            return ModelResponse(text=f"answered by {model}", input_tokens=10, output_tokens=5,
                                 total_tokens=15, provider="openai", model=model)

    monkeypatch.setattr(graph_module, "get_provider", lambda settings, name="openai": Provider())
    store = PolicyStore(policy_file or str(ROOT / "config" / "policies.json"), settings)
    graph, _ = build_gateway_graph(settings, FakeMemory(), GovernanceEngine(settings, store), FakeLimiter(), FakeAudit())
    return graph


def request(prompt="hello"):
    return {"request_id": "r1", "session_id": "s1", "application_id": "demo-app", "user_id": "u1",
            "prompt": prompt, "authorization": ""}


def test_reports_the_model_that_actually_answered(monkeypatch):
    graph = make_graph(monkeypatch, failing={"gpt-5.6-luna"})   # luna is the top choice under 'balanced'
    result = graph.invoke(request())
    assert result["response"] == "answered by gpt-5.6-terra"
    assert result["selected_model"] == "gpt-5.6-terra"          # used to say gpt-5.6-luna
    assert result["failed_models"] == ["gpt-5.6-luna"]


def test_no_failover_means_nothing_reported_as_failed(monkeypatch):
    result = make_graph(monkeypatch, failing=set()).invoke(request())
    assert result["selected_model"] == "gpt-5.6-luna" and result["failed_models"] == []


def test_failover_never_uses_a_model_the_app_is_not_allowed(monkeypatch, tmp_path):
    policy = tmp_path / "policies.json"
    policy.write_text(json.dumps({"applications": {"demo-app": {"allowed_models": ["gpt-5.6-luna"]}}}), encoding="utf-8")
    graph = make_graph(monkeypatch, failing={"gpt-5.6-luna"}, policy_file=str(policy))
    with pytest.raises(RuntimeError, match="ALL_MODELS_FAILED"):
        graph.invoke(request())          # must NOT quietly fall over to terra or sol
