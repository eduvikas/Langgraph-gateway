"""Turn raw usage records into the numbers leadership cares about."""
from collections import Counter, defaultdict

from .config import APPS, FLEET, FLEET_DAILY_COST


def _pct(vals, p):
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(len(s) * p))], 1) if s else 0.0


def summarize(recs, gw):
    ok = [r for r in recs if r["status"] == "ok"]
    summary = {
        "calls": len(recs), "ok": len(ok),
        "blocked": sum(r["status"] == "blocked" for r in recs),
        "errors": sum(r["status"] == "error" for r in recs),
        "blocked_by_reason": dict(Counter(r["reason"] for r in recs if r["status"] == "blocked")),
        "api_cost": round(sum(r["cost"] for r in recs), 2),
        "wasted_cost": round(sum(r["cost"] for r in recs if r["wasted"]), 2),
        "list_cost": round(sum(r["list_cost"] for r in recs), 2),
        "quality": round(sum(r["quality"] for r in ok if r["quality"] is not None) / max(1, len(ok)), 4),
        "latency_p50": _pct([r["latency_ms"] for r in ok], 0.5),
        "latency_p95": _pct([r["latency_ms"] for r in ok], 0.95),
        "policy_violations": sum(r["policy_violation"] for r in recs),
        "pii_in_prompt": sum(r["pii_in_prompt"] for r in recs),
        "pii_external": sum(r["pii_external"] for r in recs),
        "pii_redactions": sum(r["pii_redactions"] for r in recs),
        "fallbacks": sum(r["fallback"] for r in recs),
        "prompt_cache_tokens": sum(r["cached_in"] for r in recs),
        "breaker_trips": len(gw.breaker.tripped_runs),
    }
    cacheable_calls = sum(1 for r in recs if APPS[r["app"]].cacheable and r["status"] != "blocked")
    hits = sum(1 for r in ok if r["cache"])
    summary["cache"] = {"exact": sum(r["cache"] == "exact" for r in ok),
                        "semantic": sum(r["cache"] == "semantic" for r in ok),
                        "hit_rate": round(hits / max(1, cacheable_calls), 4)}

    by_app = {}
    for name, app in APPS.items():
        rows = [r for r in recs if r["app"] == name]
        good = [r for r in rows if r["status"] == "ok"]
        outcomes = sum(1 for r in good if not r["wasted"]) / app.calls_per_outcome
        cost = sum(r["cost"] for r in rows)
        by_app[name] = {
            "team": app.team, "use_case": app.use_case, "unit": app.unit, "calls": len(rows),
            "cost": round(cost, 2), "outcomes": round(outcomes), "budget": app.daily_budget,
            "cost_per_outcome": round(cost / outcomes, 5) if outcomes else None,
            "wasted_cost": round(sum(r["cost"] for r in rows if r["wasted"]), 2),
            "blocked": sum(r["status"] == "blocked" for r in rows),
            "tiers": dict(Counter(r["tier"] for r in good)),
        }
    summary["by_app"] = by_app

    tiers = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
    hourly = {t: [0] * 24 for t in ("self", "small", "mid", "frontier", "cache")}
    for r in ok:
        t = tiers[r["tier"]]
        t["calls"] += 1
        t["tokens"] += r["in_tokens"] + r["out_tokens"]
        t["cost"] = round(t["cost"] + r["cost"], 6)
        hourly[r["tier"]][r["hour"]] += r["in_tokens"] + r["out_tokens"]
    summary["by_tier"] = dict(tiers)
    summary["hourly_tokens"] = hourly
    self_tokens = tiers["self"]["tokens"] if "self" in tiers else 0
    cap_day = FLEET["capacity_tokens_per_min"] * 1440
    summary["fleet"] = {"tokens": self_tokens, "utilization": round(self_tokens / cap_day, 4),
                        "daily_cost": FLEET_DAILY_COST,
                        "hourly_capacity": FLEET["capacity_tokens_per_min"] * 60,
                        "capacity_per_min": FLEET["capacity_tokens_per_min"],
                        "cost_per_m": round(FLEET_DAILY_COST / (self_tokens / 1e6), 3) if self_tokens else None}

    routed = [r for r in recs if r["complexity_pred"] and r["tier"] not in (None, "cache")]
    conf = {t: Counter() for t in ("easy", "medium", "hard")}
    for r in routed:
        conf[r["complexity_true"]][r["complexity_pred"]] += 1
    summary["router"] = {"accuracy": round(sum(r["complexity_true"] == r["complexity_pred"] for r in routed)
                                           / max(1, len(routed)), 4),
                         "confusion": {k: dict(v) for k, v in conf.items()}}
    summary["events"] = gw.events
    return summary
