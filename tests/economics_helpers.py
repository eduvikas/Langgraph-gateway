"""Shared fakes for the token-economics tests: a pipeline wired to a fake provider and a real
SQLite ledger, recording usage through the same code the chat route uses."""
import uuid
from pathlib import Path

import app.gateway.graph as graph_module
from app.config import Settings
from app.economics.accounting import record_usage
from app.economics.budget import BudgetService
from app.gateway.graph import build_gateway_graph
from app.governance.engine import GovernanceEngine
from app.policy.store import PolicyStore
from app.providers.base import ModelResponse
from app.usage.ledger import UsageLedger

ROOT = Path(__file__).resolve().parent.parent


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


class ChatRequest:
    def __init__(self, application_id, session_id, user_id):
        self.application_id, self.session_id, self.user_id = application_id, session_id, user_id


def make_settings(**overrides):
    base = dict(openai_api_key="sk-test-not-real", mock_provider_enabled=False, auth_enabled=False,
                allowed_models_raw="gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna")
    base.update(overrides)
    return Settings(**base)


class Harness:
    def __init__(self, monkeypatch, tmp_path, *, tokens=(1000, 500), text="a perfectly good answer", policy_file=None,
                 settings=None, budgeted=False, **graph_kwargs):
        # Budget reservations live in DATABASE_URL (default ./gateway.db). Point every harness at a
        # per-test database so reserved/spent amounts cannot leak between tests or runs.
        self.settings = (settings or make_settings()).model_copy(
            update={"database_url": f"sqlite:///{tmp_path / 'gateway.db'}"})
        self.tokens, self.text, self.calls, self.budgeted = tokens, text, [], budgeted
        harness = self

        class Provider:
            def generate(self, prompt, history, model, max_output_tokens):
                harness.calls.append(model)
                return ModelResponse(text=harness.text, input_tokens=harness.tokens[0], output_tokens=harness.tokens[1],
                                     total_tokens=sum(harness.tokens), provider="mock" if model.startswith("mock") else "openai",
                                     model=model)

        monkeypatch.setattr(graph_module, "get_provider", lambda settings, name="openai": Provider())
        self.ledger = UsageLedger(f"sqlite:///{tmp_path / 'usage.db'}")
        self.memory = FakeMemory()
        self.policies = PolicyStore(policy_file or str(ROOT / "config" / "policies.json"), self.settings)
        self.governance = GovernanceEngine(self.settings, self.policies)
        self.graph, _ = build_gateway_graph(self.settings, self.memory, self.governance, FakeLimiter(), FakeAudit(),
                                            **self.extra(graph_kwargs))

    def extra(self, graph_kwargs):
        if self.budgeted:
            graph_kwargs = {**graph_kwargs, "budget": BudgetService(self.settings, self.policies, self.ledger)}
        return graph_kwargs

    def ask(self, prompt="hello", app="demo-app", session="s1", user="u1"):
        result = self.graph.invoke({"request_id": uuid.uuid4().hex, "session_id": session, "application_id": app,
                                    "user_id": user, "prompt": prompt, "authorization": ""})
        record_usage(self.ledger, request_id=uuid.uuid4().hex, request=ChatRequest(app, session, user),
                     result=result, default_model="gpt-5.6-sol")
        return result
