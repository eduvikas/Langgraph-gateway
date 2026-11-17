"""One way to configure a gateway under test, shared by every pipeline-level test.

Previously the failover fixture and the economics harness each configured settings, profiles and policies their own
way, and both leaned on ambient state: the repo's `config/policies.json`, the built-in default profiles, and whatever
`Settings()` picked up from the environment. This module makes all three explicit:

* settings   - every environment-sensitive field is pinned (`make_test_settings`)
* profiles   - GPT profiles are declared here, not inherited (`GPT_PROFILES`)
* policies   - written to the test's tmp_path, aligned with the profiles (`write_policy_file`)
"""
import json
from pathlib import Path

import app.gateway.graph as graph_module
from app.config import Settings
from app.gateway.graph import build_gateway_graph
from app.governance.engine import GovernanceEngine
from app.policy.store import PolicyStore
from app.providers.base import ModelResponse
from app.routing.profiles import build_model_profiles

GPT_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
APPLICATIONS = ("demo-app", "contract-agent", "sre-agent")

# Explicit on purpose: under 'balanced' luna ranks first, then terra, then sol; coding/reasoning work prefers sol/terra.
GPT_PROFILES = [
    {"provider": "openai", "model": "gpt-5.6-sol", "quality": 0.95, "latency": 0.70, "capabilities": ["general", "reasoning", "coding"]},
    {"provider": "openai", "model": "gpt-5.6-terra", "quality": 0.92, "latency": 0.82, "capabilities": ["general", "reasoning", "coding"]},
    {"provider": "openai", "model": "gpt-5.6-luna", "quality": 0.82, "latency": 0.96, "capabilities": ["general", "general_fast"]},
]

# Per-application policy used by tests (mirrors the shipped config's shape, but owned by the tests).
_APP_POLICY = {
    "demo-app": {"max_requests_per_session": 50, "max_prompt_chars": 20000, "max_data_classification": "confidential",
                 "allow_pii": True, "daily_budget_usd": 5.0},
    "contract-agent": {"max_requests_per_session": 100, "max_prompt_chars": 30000, "max_data_classification": "confidential",
                       "allow_pii": True, "daily_budget_usd": 10.0},
    "sre-agent": {"max_requests_per_session": 100, "max_prompt_chars": 20000, "max_data_classification": "restricted",
                  "allow_pii": False, "daily_budget_usd": 10.0, "allow_cache": False},
}


def make_test_settings(**overrides) -> Settings:
    """Settings that do not depend on the environment: nothing here is left to a default that reads `os.getenv`."""
    base = dict(
        app_env="local", openai_api_key="sk-test-not-real", openai_model="gpt-5.6-sol",
        mock_provider_enabled=False, auth_enabled=False, allow_insecure_local_auth=True,
        allowed_applications_raw=",".join(APPLICATIONS), allowed_models_raw=",".join(GPT_MODELS),
        model_profiles_json=json.dumps(GPT_PROFILES), model_pricing_json="",
        baseline_model="gpt-5.6-sol", mock_pricing_model="", default_daily_budget_usd=0.0,
        budget_output_estimate_tokens=500, budget_alert_threshold=0.8,
        max_prompt_chars=20000, max_output_tokens=2000, max_requests_per_session=50,
        block_secrets=True, block_prompt_injection=True, injection_strict=False,
        rate_limiter_backend="memory", cache_enabled=True, cache_backend="memory",
        circuit_failure_threshold=3, circuit_recovery_seconds=30,
    )
    base.update(overrides)
    return Settings(**base)


def write_policy_file(tmp_path: Path, models=None, *, settings=None, name="policies.json", **per_app) -> str:
    """Write an isolated policy file. Permitted models default to the models the router can actually serve for
    `settings`, so policy and profiles agree unless a test deliberately makes them disagree.
    `per_app` maps application -> field overrides (e.g. ``**{"demo-app": {"allowed_models": ["gpt-5.6-luna"]}}``)."""
    if models is None:
        models = [p.model for p in build_model_profiles(settings or make_test_settings()) if p.enabled]
    apps = {}
    for app_id, base in _APP_POLICY.items():
        apps[app_id] = {"enabled": True, "allowed_models": list(models), "required_roles": ["developer", "operator"],
                        "allow_secrets": False, "allow_prompt_injection": False, **base, **per_app.get(app_id, {})}
    path = tmp_path / name
    path.write_text(json.dumps({"applications": apps}), encoding="utf-8")
    return str(path)


class FakeMemory:
    """Keeps real per-session history, so multi-turn behaviour is genuine."""
    def __init__(self): self.rows = {}
    def increment_request_count(self, *a, **k): return 1
    def get_history(self, session_id, *a, **k): return list(self.rows.get(session_id, []))
    def append(self, session_id, role, content, *a, **k): self.rows.setdefault(session_id, []).append({"role": role, "content": content})


class FakeLimiter:
    def allow(self, key): return True, 59


class FakeAudit:
    def record(self, **k): return None


def install_provider(monkeypatch, generate):
    """Replace the provider factory. `generate(model, prompt, history)` returns a ModelResponse or raises."""
    class Provider:
        def generate(self, prompt, history, model, max_output_tokens):
            return generate(model, prompt, history)
    monkeypatch.setattr(graph_module, "get_provider", lambda settings, name="openai": Provider())


def model_response(model, text="ok", tokens=(10, 5)):
    return ModelResponse(text=text, input_tokens=tokens[0], output_tokens=tokens[1], total_tokens=sum(tokens),
                         provider="mock" if model.startswith("mock") else "openai", model=model)


def build_graph(settings, policy_file, *, memory=None, **graph_kwargs):
    store = PolicyStore(policy_file, settings)
    governance = GovernanceEngine(settings, store)
    graph, _ = build_gateway_graph(settings, memory or FakeMemory(), governance, FakeLimiter(), FakeAudit(), **graph_kwargs)
    return graph, store, governance
