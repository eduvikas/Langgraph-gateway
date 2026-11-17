"""Response cache: hits are free and recorded as such, and it is safe to share."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.control_tower.metrics import ControlTower
from app.economics.cache import (InMemoryResponseCache, RedisResponseCache, build_response_cache, make_cache_key)
from app.main import app
from tests.economics_helpers import Harness, make_settings
from tests.test_budgets import ROW, harness as budget_harness, policies


class FakeClock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


class FakeRedis:
    def __init__(self): self.data, self.ttls = {}, {}
    def get(self, key): return self.data.get(key)
    def setex(self, key, ttl, value): self.data[key], self.ttls[key] = value, ttl


def cached_harness(monkeypatch, tmp_path, **kw):
    cache = InMemoryResponseCache(ttl_seconds=3600, max_entries=100)
    return Harness(monkeypatch, tmp_path, cache=cache, **kw), cache


# ---- the cache itself ---------------------------------------------------------------------------
def test_entries_expire_after_the_ttl():
    clock = FakeClock(); cache = InMemoryResponseCache(ttl_seconds=60, max_entries=10, clock=clock)
    cache.set("k", {"a": 1}); assert cache.get("k") == {"a": 1}
    clock.now += 61; assert cache.get("k") is None


def test_least_recently_used_entry_is_evicted():
    cache = InMemoryResponseCache(ttl_seconds=60, max_entries=2)
    cache.set("a", 1); cache.set("b", 2); cache.get("a"); cache.set("c", 3)
    assert cache.get("a") == 1 and cache.get("b") is None and cache.get("c") == 3


def test_key_separates_applications_models_prompts_and_history():
    base = make_cache_key("app", "m", "hello", [])
    assert make_cache_key("app", "m", "  hello  ", []) == base                      # whitespace-trimmed
    assert len({base, make_cache_key("other", "m", "hello", []), make_cache_key("app", "m2", "hello", []),
                make_cache_key("app", "m", "hello!", []), make_cache_key("app", "m", "hello", [{"role": "user", "content": "x"}])}) == 5


def test_redis_backend_round_trips_with_a_prefix_and_ttl():
    client = FakeRedis(); cache = RedisResponseCache(client, ttl_seconds=120)
    cache.set("k", {"response": "hi"})
    assert cache.get("k") == {"response": "hi"} and cache.get("missing") is None
    assert list(client.ttls.values()) == [120] and all(k.startswith("gateway:response:") for k in client.data)


def test_a_redis_outage_is_a_miss_not_an_error():
    class Broken:
        def get(self, *a): raise ConnectionError("down")
        def setex(self, *a): raise ConnectionError("down")
    cache = RedisResponseCache(Broken())
    assert cache.get("k") is None
    cache.set("k", {"x": 1})            # must not raise


def test_builder_honours_the_settings(monkeypatch):
    assert build_response_cache(make_settings(cache_enabled=False)) is None
    assert isinstance(build_response_cache(make_settings()), InMemoryResponseCache)
    fake = FakeRedis(); monkeypatch.setattr("redis.from_url", lambda url, decode_responses=True: fake)
    built = build_response_cache(make_settings(cache_backend="redis", redis_url="redis://x"))
    assert isinstance(built, RedisResponseCache) and built.client is fake


# ---- through the pipeline -----------------------------------------------------------------------
def test_second_identical_request_is_served_free_from_the_cache(monkeypatch, tmp_path):
    h, _ = cached_harness(monkeypatch, tmp_path, tokens=(1000, 500))
    first, second = h.ask("What is our refund policy?", session="a"), h.ask("What is our refund policy?", session="b")
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert len(h.calls) == 1                                            # the model was called once
    assert second["response"] == first["response"] and second["selected_model"] == first["selected_model"]
    assert (second["cost_usd"], second["tokens_avoided"], second["total_tokens"]) == (0.0, 1500, 0)
    assert second["baseline_cost_usd"] == 0.014 and second["avoided_cost_usd"] == 0.0008
    row = h.ledger.recent(1)[0]
    assert row["cache_hit"] is True and row["total_tokens"] == 0 and row["tokens_avoided"] == 1500


def test_savings_split_into_cache_and_model_choice(monkeypatch, tmp_path):
    h, _ = cached_harness(monkeypatch, tmp_path, tokens=(1000, 500))
    h.ask("same question", session="a"); h.ask("same question", session="b")
    t = ControlTower(h.ledger, None, None).economics()["totals"]
    assert t["cost_usd"] == pytest.approx(0.0008) and t["baseline_cost_usd"] == pytest.approx(0.028)
    assert t["savings_usd"] == pytest.approx(0.0272) and t["savings_from_cache_usd"] == pytest.approx(0.0008)
    assert t["savings_from_model_choice_usd"] == pytest.approx(0.0264) and t["cache_hit_rate"] == 0.5


def test_applications_never_share_cached_answers(monkeypatch, tmp_path):
    h, _ = cached_harness(monkeypatch, tmp_path)
    h.ask("same question", app="demo-app", session="a")
    assert h.ask("same question", app="contract-agent", session="b")["cache_hit"] is False and len(h.calls) == 2


def test_history_matters_so_conversations_do_not_share_answers(monkeypatch, tmp_path):
    h, _ = cached_harness(monkeypatch, tmp_path)
    h.ask("hello", session="a")
    assert h.ask("hello", session="a")["cache_hit"] is False            # same session: history now differs
    assert h.ask("hello", session="b")["cache_hit"] is True             # a fresh conversation matches the first


def test_pii_is_never_cached_or_served(monkeypatch, tmp_path):
    h, cache = cached_harness(monkeypatch, tmp_path)
    prompt = "Please look up the account for jane.doe@example.com"
    h.ask(prompt, session="a"); second = h.ask(prompt, session="b")
    assert second["cache_hit"] is False and second["cache_skip"] == "sensitive_classification" and len(h.calls) == 2
    assert not cache._items


def test_application_can_opt_out(monkeypatch, tmp_path):
    h, cache = cached_harness(monkeypatch, tmp_path)                    # sre-agent has allow_cache: false in config/policies.json
    h.ask("is the db healthy?", app="sre-agent", session="a"); second = h.ask("is the db healthy?", app="sre-agent", session="b")
    assert second["cache_hit"] is False and second["cache_skip"] == "disabled_by_policy" and not cache._items


def test_answers_that_fail_evaluation_are_not_stored(monkeypatch, tmp_path):
    h, cache = cached_harness(monkeypatch, tmp_path, text="")
    first = h.ask("a question", session="a")
    assert first["evaluation"]["passed"] is False and not cache._items
    assert h.ask("a question", session="b")["cache_hit"] is False


def test_entries_expire_in_the_pipeline(monkeypatch, tmp_path):
    clock = FakeClock(); cache = InMemoryResponseCache(ttl_seconds=60, max_entries=10, clock=clock)
    h = Harness(monkeypatch, tmp_path, cache=cache)
    h.ask("q", session="a"); assert h.ask("q", session="b")["cache_hit"] is True
    clock.now += 61
    assert h.ask("q", session="c")["cache_hit"] is False


def test_governance_runs_before_the_cache(monkeypatch, tmp_path):
    """A cached answer must not be served to someone governance would reject."""
    policy = policies(tmp_path, **{"demo-app": {"required_roles": ["operator"]}})
    cache = InMemoryResponseCache()
    h = Harness(monkeypatch, tmp_path, cache=cache, policy_file=policy)
    cache.set(make_cache_key("demo-app", "gpt-5.6-luna", "secret-ish question", []),
              {"response": "cached answer", "provider": "openai", "model": "gpt-5.6-luna", "input_tokens": 1, "output_tokens": 1,
               "total_tokens": 2, "evaluation": {}})
    result = h.ask("secret-ish question")                               # default role 'developer' lacks 'operator'
    assert result["decision"] == "BLOCK" and result.get("response") != "cached answer" and not h.calls


def test_a_cache_hit_is_still_served_after_the_budget_is_spent(monkeypatch, tmp_path):
    cache = InMemoryResponseCache()
    h = budget_harness(monkeypatch, tmp_path, limit=0.002, cache=cache)
    assert h.ask("repeat me", session="a")["decision"] == "ALLOW"       # cached; costs 0.0008
    h.ledger.record(application_id="demo-app", cost_usd=50.0, **ROW)   # budget now exhausted
    hit = h.ask("repeat me", session="b")
    assert hit["decision"] == "ALLOW" and hit["cache_hit"] is True and hit["cost_usd"] == 0.0
    assert h.ask("a different question", session="c")["decision"] == "BLOCK"


def test_end_to_end_through_the_real_route():
    client, uid = TestClient(app), uuid.uuid4().hex
    ask = lambda n: client.post("/v1/chat", json={"session_id": f"c{n}-{uid}", "application_id": "demo-app", "user_id": "u1",
                                                   "prompt": "cache check " + uid}).json()
    first, second = ask(1), ask(2)
    assert first["cache_hit"] is False and second["cache_hit"] is True and second["economics"]["cache_hit"] is True
