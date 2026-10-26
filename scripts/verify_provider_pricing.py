"""Validate configured model pricing metadata without pretending to verify live prices.

Official prices must be manually checked against each provider's current pricing page.
This command checks that the local config is complete, finite, dated, and not stale.
"""
from __future__ import annotations
import json
import math
from datetime import date
from pathlib import Path
import os
import sys


def main() -> int:
    raw = os.getenv("MODEL_PRICING_JSON", "").strip()
    if not raw:
        print("ERROR: MODEL_PRICING_JSON is empty. See .env.production.example.", file=sys.stderr)
        return 2
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: MODEL_PRICING_JSON is invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(entries, dict) or not entries:
        print("ERROR: pricing config must be a non-empty JSON object", file=sys.stderr)
        return 2
    failures = []
    today = date.today()
    print("Configured model pricing metadata (not a live provider price check):")
    for model, item in sorted(entries.items()):
        try:
            input_rate = float(item["input_per_1m"])
            output_rate = float(item["output_per_1m"])
            source = str(item["source"])
            verified = date.fromisoformat(str(item["verified_on"]))
            if not math.isfinite(input_rate) or not math.isfinite(output_rate) or input_rate < 0 or output_rate < 0:
                raise ValueError("rates must be finite and non-negative")
            if not source.startswith("https://") or any(x in source.lower() for x in ("replace_with", "placeholder", "example.com")):
                raise ValueError("source must be a real HTTPS provider pricing page")
            age = (today - verified).days
            if age < 0:
                raise ValueError("verified_on cannot be in the future")
            max_age = int(os.getenv("PRICING_MAX_AGE_DAYS", "30"))
            if age > max_age:
                raise ValueError(f"pricing metadata is stale ({age} days; max {max_age})")
            if input_rate == 0 and output_rate == 0 and model != "mock-general":
                raise ValueError("real models cannot have both rates set to zero")
            print(f"  OK  {model}: input=${input_rate:g}/1M, output=${output_rate:g}/1M; verified={verified}; age={age}d; source={source}")
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"{model}: {exc}")
            print(f"  FAIL {model}: {exc}")
    if failures:
        print(f"\nPricing metadata validation failed for {len(failures)} model(s).", file=sys.stderr)
        return 1
    print("\nMetadata checks passed. A human must still confirm rates on the linked official pricing page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
