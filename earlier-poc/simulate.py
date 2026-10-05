"""Run the same simulated day through four gateway configurations and compare.

    python simulate.py                 # default day (~14.6k model calls)
    python simulate.py --scale 5       # 5x traffic
"""
import argparse
import json
import time

from gateway.config import APPS, FLEET_DAILY_COST
from gateway.core import Features, Gateway
from gateway.meter import Meter
from gateway.metrics import summarize
from gateway.workload import build_workload

SCENARIOS = [
    ("Direct to frontier (today)", Features()),
    ("+ Smart routing", Features(routing=True)),
    ("+ Caching", Features(routing=True, response_cache=True, prompt_cache=True)),
    ("+ Budgets and circuit breaker", Features(routing=True, response_cache=True, prompt_cache=True,
                                               guardrails=True, budgets=True, breaker=True, fallback=True)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--db", default="usage.db")
    args = ap.parse_args()

    reqs = build_workload(args.seed, args.scale)
    meter = Meter(args.db)
    out = {"meta": {"requests": len(reqs), "seed": args.seed, "scale": args.scale,
                    "fleet_daily_cost": FLEET_DAILY_COST,
                    "apps": {n: {"team": a.team, "use_case": a.use_case, "unit": a.unit,
                                 "api_key": a.api_key, "budget": a.daily_budget} for n, a in APPS.items()}},
           "scenarios": []}

    print(f"Simulating {len(reqs):,} model calls from {len(APPS)} applications\n")
    base_cost = None
    for name, feats in SCENARIOS:
        t0 = time.time()
        gw = Gateway(feats, scenario=name, meter=meter)
        for r in reqs:
            gw.handle(r)
        s = summarize(gw.results, gw)
        s["name"], s["features"] = name, vars(feats)
        out["scenarios"].append(s)
        base_cost = base_cost or s["api_cost"]
        saved = 100 * (1 - s["api_cost"] / base_cost)
        print(f"{name:34s} API spend ${s['api_cost']:>8,.2f}  saved {saved:5.1f}%  quality {s['quality']:.3f}  "
              f"p95 {s['latency_p95']:>6.0f} ms  blocked {s['blocked']:>4d}  errors {s['errors']:>3d}  ({time.time()-t0:.1f}s)")
    meter.flush()
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nWrote {args.out} and {args.db}")


if __name__ == "__main__":
    main()
