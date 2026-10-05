"""The gateway: one entry point that meters, protects, caches, routes and bills every call."""
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .backends import Fleet, price
from .cache import ResponseCache
from .config import (APPS, API_ERROR_RATE, CACHE_HIT_MS, FRONTIER, GATEWAY_OVERHEAD_MS, MODELS,
                     PROMPT_CACHE_TTL_S, SOFT_BUDGET)
from .guardrails import CircuitBreaker, redact
from .router import classify, pick_model


@dataclass
class Features:
    routing: bool = False
    response_cache: bool = False
    prompt_cache: bool = False
    guardrails: bool = False     # PII redaction + data-residency policy
    budgets: bool = False
    breaker: bool = False
    fallback: bool = False

    def managed(self):
        return any(vars(self).values())


@dataclass
class Request:
    id: int
    ts: float                    # seconds since start of the simulated day
    app: str
    prompt: str
    in_tokens: int
    out_tokens: int
    sys_tokens: int
    true_complexity: str         # ground truth, used only to score quality and router accuracy
    run_id: Optional[str] = None
    wasted: bool = False         # part of a runaway loop (ground truth for reporting)
    has_pii: bool = False


class Budgets:
    def __init__(self):
        self.spent = defaultdict(float)

    def state(self, app, ts):
        budget, spent = APPS[app].daily_budget, self.spent[(app, int(ts // 86400))]
        if spent >= budget:
            return "hard"
        return "soft" if spent >= SOFT_BUDGET * budget else "ok"

    def add(self, app, ts, cost):
        self.spent[(app, int(ts // 86400))] += cost


class Gateway:
    def __init__(self, features, scenario="", meter=None):
        self.f, self.scenario, self.meter = features, scenario, meter
        self.cache, self.fleet = ResponseCache(), Fleet()
        self.breaker, self.budgets = CircuitBreaker(), Budgets()
        self.prefix_seen = {}
        self.results, self.events = [], []
        self._budget_flags, self._tripped_logged = set(), set()

    # -- helpers -----------------------------------------------------------------------------
    def _event(self, ts, kind, app, detail):
        if len([e for e in self.events if e["kind"] == kind]) < 12:
            self.events.append({"ts": round(ts), "kind": kind, "app": app, "detail": detail})

    def _done(self, rec):
        self.results.append(rec)
        if self.meter:
            self.meter.log(rec)
        return rec

    def _stop(self, rec, status, reason, overhead, latency=5):
        rec.update(status=status, reason=reason, latency_ms=latency + overhead)
        return self._done(rec)

    # -- main entry point ----------------------------------------------------------------------
    def handle(self, req):
        f, app, rng = self.f, APPS[req.app], random.Random(req.id)
        overhead = GATEWAY_OVERHEAD_MS if f.managed() else 0
        list_cost = price(MODELS[FRONTIER], req.in_tokens, req.out_tokens)
        rec = dict(scenario=self.scenario, req_id=req.id, ts=round(req.ts, 1), hour=int(req.ts // 3600) % 24,
                   app=app.name, team=app.team, use_case=app.use_case, run_id=req.run_id, model=None,
                   tier=None, in_tokens=req.in_tokens, out_tokens=req.out_tokens, cached_in=0, cost=0.0,
                   list_cost=round(list_cost, 6), latency_ms=0.0, status="ok", reason="", cache="",
                   complexity_true=req.true_complexity, complexity_pred="", quality=None,
                   pii_in_prompt=int(req.has_pii), pii_redactions=0, pii_external=0, policy_violation=0,
                   wasted=int(req.wasted), fallback=0)

        # 1. guardrails: strip PII and secrets before anything leaves the building
        prompt = req.prompt
        if f.guardrails:
            prompt, found = redact(prompt)
            rec["pii_redactions"] = sum(found.values())

        # 2. circuit breaker for agent loops
        if f.breaker and req.run_id and self.breaker.tripped(req.run_id):
            if req.run_id not in self._tripped_logged:
                self._tripped_logged.add(req.run_id)
                self._event(req.ts, "circuit_breaker", app.name,
                            f"{req.run_id} stopped after {self.breaker.calls[req.run_id]} calls")
            return self._stop(rec, "blocked", "circuit_breaker", overhead)

        # 3. budgets: soft limit routes cheaper, hard limit blocks
        state = self.budgets.state(app.name, req.ts) if f.budgets else "ok"
        if state != "ok" and (app.name, state) not in self._budget_flags:
            self._budget_flags.add((app.name, state))
            self._event(req.ts, f"budget_{state}", app.name, f"{state} limit reached")
        if state == "hard":
            return self._stop(rec, "blocked", "budget_exhausted", overhead)

        # 4. response cache
        if f.response_cache and app.cacheable:
            hit = self.cache.get(app.name, prompt, req.ts)
            if hit:
                kind, entry = hit
                rec.update(model="cache", tier="cache", cache=kind, latency_ms=CACHE_HIT_MS + overhead,
                           quality=entry["quality"], complexity_pred=entry["pred"])
                if req.run_id:
                    self.breaker.record(req.run_id, 0)
                return self._done(rec)

        # 5. routing
        pred = classify(prompt, req.in_tokens) if (f.routing or f.fallback) else ""
        rec["complexity_pred"] = pred
        if f.routing:
            model = pick_model(app, pred, state == "soft", self.fleet, req.ts,
                               req.in_tokens + req.out_tokens, f.guardrails)
            if model is None:
                return self._stop(rec, "blocked", "no_eligible_model", overhead)
        else:
            model = MODELS[FRONTIER]

        # 6. provider failure: fall back to the next best allowed model, or surface the error
        fell_back = False
        if model.tier != "self" and rng.random() < API_ERROR_RATE:
            alt = None
            if f.fallback:
                alt = pick_model(app, pred, False, self.fleet, req.ts, req.in_tokens + req.out_tokens,
                                 f.guardrails, exclude={model.name}, mode="fallback")
            if alt is None:
                return self._stop(rec, "error", "provider_error", overhead, latency=1500)
            self._event(req.ts, "fallback", app.name, f"{model.name} failed, served by {alt.name}")
            model, fell_back = alt, True
            rec["fallback"] = 1

        # 7. execute (mock backend)
        cached_in = 0
        if f.prompt_cache and model.tier != "self" and req.sys_tokens:
            key = (app.name, model.name)
            if req.ts - self.prefix_seen.get(key, -1e9) <= PROMPT_CACHE_TTL_S:
                cached_in = req.sys_tokens
            self.prefix_seen[key] = req.ts
        load = 1.0
        if model.tier == "self":
            load = 1 + 1.5 * self.fleet.utilization(req.ts) ** 3
            self.fleet.add(req.ts, req.in_tokens + req.out_tokens)
        cost = price(model, req.in_tokens, req.out_tokens, cached_in)
        latency = (model.ttft_ms + req.out_tokens * model.ms_per_token) * load * rng.uniform(0.85, 1.25)
        latency += overhead + (1500 if fell_back else 0)
        quality = model.quality[req.true_complexity]

        rec.update(model=model.name, tier=model.tier, cached_in=cached_in, cost=round(cost, 6),
                   latency_ms=round(latency, 1), quality=quality,
                   pii_external=int(req.has_pii and model.region != "onprem" and not f.guardrails),
                   policy_violation=int(bool(app.allowed_regions) and model.region not in app.allowed_regions))

        if f.response_cache and app.cacheable:
            self.cache.put(app.name, prompt, req.ts, dict(model=model.name, tier=model.tier,
                                                          quality=quality, pred=pred))
        self.budgets.add(app.name, req.ts, cost)
        if req.run_id:
            self.breaker.record(req.run_id, req.in_tokens + req.out_tokens)
        return self._done(rec)
