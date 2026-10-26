"""
Cost-per-outcome report — the number leadership actually acts on.

Cost-per-token is a finance-team argument. "Resolving a support ticket now
costs $X instead of $Y" is the argument that survives being repeated in a
hallway. This runs a batch of simulated traffic and reports both.

Run:
    python roi_report.py
    python roi_report.py --requests 500
    python roi_report.py --csv roi_report.csv
"""
import argparse
import csv
import random

from gateway_graph import AIGateway, APPS
from demo_runner import SAMPLE_PROMPTS


def run(n_requests: int) -> AIGateway:
    """Mixes genuine repeat questions (cache-eligible) with unique ones, so
    the cache hit rate looks like real traffic rather than an artificially
    perfect number."""
    gateway = AIGateway()
    for i in range(n_requests):
        app_id = random.choice(list(APPS.keys()))
        base = random.choice(SAMPLE_PROMPTS)
        prompt = base if random.random() < 0.35 else f"{base} (ref #{i}-{random.randint(1000, 9999)})"
        gateway.process(app_id, prompt)
    return gateway


def print_report(gateway: AIGateway):
    rows = gateway.cost_per_outcome()
    header = f"{'App':<26}{'Outcome':<20}{'Delivered':<11}{'Cost / outcome':<16}{'Without gateway':<18}{'Reduction'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        base = r["baseline_cost_per_outcome"]
        reduction = (1 - r["cost_per_outcome"] / base) * 100 if base else 0
        print(
            f"{r['app']:<26}{r['outcome_label']:<20}{r['outcomes']:<11}"
            f"${r['cost_per_outcome']:<15.5f}${base:<17.5f}{reduction:.0f}%"
        )
    print(gateway.summary())


def write_csv(gateway: AIGateway, path: str):
    rows = gateway.cost_per_outcome()
    fieldnames = ["app", "outcome_label", "outcomes", "spend", "cost_per_outcome", "baseline_cost_per_outcome"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {path} — ready to paste into a sheet or slide.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cost-per-outcome ROI report")
    parser.add_argument("--requests", type=int, default=300, help="number of simulated requests to run")
    parser.add_argument("--csv", type=str, default=None, help="optional path to also write a CSV")
    args = parser.parse_args()

    gateway = run(args.requests)
    print_report(gateway)
    if args.csv:
        write_csv(gateway, args.csv)
