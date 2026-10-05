"""
In-memory state for the AI Gateway service: per-app spend, per-run budgets
and step counts, the response cache, and outcome/tier counters.

Deliberately simple — one process, plain dicts, a single lock — so the
whole thing is readable in one sitting. Before running more than one
worker or instance, swap this for Redis: INCRBYFLOAT for spend, a Lua
script (or MULTI/WATCH) for the check-then-spend to be truly atomic, and
a real TTL'd cache. The comments below mark exactly where that swap goes.
"""
import hashlib
import threading
import time
from dataclasses import dataclass, field


@dataclass
class RunLimits:
    max_budget: float = 5.0
    max_steps: int = 25
    spend: float = 0.0
    steps: int = 0
    created_at: float = field(default_factory=time.time)


class StateStore:
    def __init__(self):
        self._lock = threading.Lock()  # <- becomes a Redis transaction in production
        self.app_spend: dict[str, float] = {}
        self.app_baseline: dict[str, float] = {}
        self.app_outcomes: dict[str, int] = {}
        self.app_blocked: dict[str, int] = {}
        self.runs: dict[str, RunLimits] = {}
        self.cache: dict[str, dict] = {}  # <- becomes Redis GET/SET with a TTL
        self.tier_counts = {"small": 0, "mid": 0, "frontier": 0, "cache": 0}
        self.requests = 0
        self.cache_hits = 0

    # ---- app-level spend ----
    def app_spend_get(self, app_id: str) -> float:
        return self.app_spend.get(app_id, 0.0)

    def app_add_spend(self, app_id: str, amount: float):
        with self._lock:
            self.app_spend[app_id] = self.app_spend.get(app_id, 0.0) + amount

    def app_add_baseline(self, app_id: str, amount: float):
        with self._lock:
            self.app_baseline[app_id] = self.app_baseline.get(app_id, 0.0) + amount

    def app_add_outcome(self, app_id: str):
        with self._lock:
            self.app_outcomes[app_id] = self.app_outcomes.get(app_id, 0) + 1

    def app_add_blocked(self, app_id: str):
        with self._lock:
            self.app_blocked[app_id] = self.app_blocked.get(app_id, 0) + 1

    # ---- run-level budget / step count ----
    def get_run(self, run_id: str, max_budget: float | None = None, max_steps: int | None = None) -> RunLimits:
        with self._lock:
            if run_id not in self.runs:
                self.runs[run_id] = RunLimits(
                    max_budget=max_budget if max_budget is not None else 5.0,
                    max_steps=max_steps if max_steps is not None else 25,
                )
            return self.runs[run_id]

    def run_reserve(self, run_id: str, amount: float) -> bool:
        """Returns False (and reserves nothing) if this would exceed the
        run's budget or step count. Reservation happens BEFORE the model
        call using an estimated cost — see server.py for why, and for the
        known race this doesn't fully close under concurrent requests."""
        with self._lock:
            run = self.runs[run_id]
            if run.spend + amount > run.max_budget or run.steps + 1 > run.max_steps:
                return False
            run.spend += amount
            run.steps += 1
            return True

    def run_adjust_spend(self, run_id: str, delta: float):
        with self._lock:
            self.runs[run_id].spend += delta

    # ---- cache ----
    def cache_key(self, app_id: str, messages: list, tools) -> str:
        blob = repr((app_id, [(m.get("role"), m.get("content")) for m in messages], tools))
        return hashlib.sha256(blob.encode()).hexdigest()

    def cache_get(self, key: str):
        return self.cache.get(key)

    def cache_set(self, key: str, value: dict):
        self.cache[key] = value

    # ---- aggregate stats ----
    def record_tier(self, tier: str):
        with self._lock:
            self.tier_counts[tier] += 1

    def record_request(self, cache_hit: bool):
        with self._lock:
            self.requests += 1
            if cache_hit:
                self.cache_hits += 1
                self.tier_counts["cache"] += 1


store = StateStore()
