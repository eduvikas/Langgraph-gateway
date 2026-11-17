"""Shared fakes for the token-economics tests: a pipeline wired to a fake provider and a real
SQLite ledger, recording usage through the same code the chat route uses.

Configuration comes from `tests.support`: pinned settings, explicit GPT profiles, and a policy file written to the
test's own tmp_path and aligned with those profiles - never the repo's shared `config/policies.json`."""
import uuid

from app.economics.accounting import record_usage
from app.economics.budget import BudgetService
from app.usage.ledger import UsageLedger
from tests.support import (FakeAudit, FakeLimiter, FakeMemory, build_graph, install_provider, make_test_settings,
                           model_response, write_policy_file)


class ChatRequest:
    def __init__(self, application_id, session_id, user_id):
        self.application_id, self.session_id, self.user_id = application_id, session_id, user_id


def make_settings(**overrides):
    return make_test_settings(**overrides)


class Harness:
    def __init__(self, monkeypatch, tmp_path, *, tokens=(1000, 500), text="a perfectly good answer", policy_file=None,
                 settings=None, budgeted=False, failing=(), **graph_kwargs):
        # Budget reservations live in DATABASE_URL. Point every harness at a per-test database so
        # reserved/spent amounts cannot leak between tests or runs.
        self.settings = (settings or make_settings()).model_copy(
            update={"database_url": f"sqlite:///{tmp_path / 'gateway.db'}"})
        self.tokens, self.text, self.calls, self.budgeted = tokens, text, [], budgeted
        self.budget = None

        def generate(model, prompt, history):
            self.calls.append(model)
            if model in failing:
                raise RuntimeError("simulated outage " + model)
            return model_response(model, self.text, self.tokens)

        install_provider(monkeypatch, generate)
        self.ledger = UsageLedger(f"sqlite:///{tmp_path / 'usage.db'}")
        self.memory = FakeMemory()
        policy_file = policy_file or write_policy_file(tmp_path, settings=self.settings)
        if budgeted:
            # BudgetService needs the policy store the graph's governance uses, so build the store first.
            from app.policy.store import PolicyStore
            store = PolicyStore(policy_file, self.settings)
            self.budget = BudgetService(self.settings, store, self.ledger)
            graph_kwargs = {**graph_kwargs, "budget": self.budget}
        self.graph, self.policies, self.governance = build_graph(self.settings, policy_file, memory=self.memory, **graph_kwargs)

    def ask(self, prompt="hello", app="demo-app", session="s1", user="u1"):
        result = self.graph.invoke({"request_id": uuid.uuid4().hex, "session_id": session, "application_id": app,
                                    "user_id": user, "prompt": prompt, "authorization": ""})
        record_usage(self.ledger, request_id=uuid.uuid4().hex, request=ChatRequest(app, session, user),
                     result=result, default_model="gpt-5.6-sol")
        return result
