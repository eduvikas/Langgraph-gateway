"""
Scenario: a runaway agent loop hits the budget guardrail.

Fires a burst of expensive, complex requests from a single app in a tight
loop — the kind of thing an unsupervised agent does when it gets stuck
retrying. Watch the "Blocked" column flip to True once that app's daily
budget is exhausted; every later call short-circuits before it ever reaches
a model, so no cost is incurred.

Run: python scenario_runaway_agent.py
"""
import random

from gateway_graph import AIGateway, APPS

BURSTY_APP = "forecast"  # Sales forecast agent — smallest budget, easy to exhaust
RUNAWAY_PROMPT = "Re-run the full pipeline forecast with an expanded feature set and cross-validate every segment."
# A stuck agent loop tends to re-inject its whole running context on every retry,
# so token counts balloon fast compared to a normal single-shot request.
RUNAWAY_TOKEN_RANGE = (60_000, 90_000)


def main():
    gateway = AIGateway()
    app_name = APPS[BURSTY_APP]["name"]
    budget = APPS[BURSTY_APP]["daily_budget"]

    print(f"Simulating a runaway loop from: {app_name} (daily budget ${budget:.2f})\n")
    header = f"{'#':<4}{'Tier':<10}{'Tokens':<9}{'Cost':<10}{'Cumulative':<12}{'Blocked'}"
    print(header)
    print("-" * len(header))

    for i in range(1, 26):
        tokens = random.randint(*RUNAWAY_TOKEN_RANGE)
        result = gateway.process(
            BURSTY_APP, RUNAWAY_PROMPT + f" (attempt {i})",
            force_complexity="complex", force_tokens=tokens,
        )
        cumulative = gateway.spend[BURSTY_APP]
        flag = "  <-- guardrail engaged" if result["blocked"] else ""
        print(f"{i:<4}{result['tier']:<10}{result['tokens']:<9}${result['cost']:<9.4f}${cumulative:<11.4f}{result['blocked']}{flag}")

    print(gateway.summary())
    print(
        "\nWithout the budget guardrail (check_budget node), every one of these 25 calls "
        "would have gone straight to the frontier model — the gateway caught it after "
        f"the {app_name} budget was exhausted."
    )


if __name__ == "__main__":
    main()
