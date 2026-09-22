"""
Run this to see the gateway route traffic live.

Without any setup, it runs fully offline against the mock models. To see
each request as a trace in LangSmith (classify -> cache -> budget -> model,
as separate spans with real latency), set these first:

    export LANGCHAIN_TRACING_V2=true
    export LANGCHAIN_API_KEY=<your LangSmith API key>
    export LANGCHAIN_PROJECT=ai-gateway-demo

Then: python demo_runner.py
"""
import os
import random
import time

from gateway_graph import AIGateway, APPS

os.environ.setdefault("LANGCHAIN_PROJECT", "ai-gateway-demo")

# A handful of repeated prompts so the cache has something to hit, mixed
# with unique ones so most traffic still reaches a model.
SAMPLE_PROMPTS = [
    "How do I reset my password?",
    "What is our expense reimbursement policy?",
    "Summarize this 40-page vendor contract for key liability clauses.",
    "Review this pull request for style violations.",
    "Forecast Q3 pipeline given the last 6 months of deal data.",
    "Walk through the steps to redeploy the staging environment.",
    "What's our current PTO carry-over policy?",
    "Draft release notes for the payments service migration.",
]


def main(n_requests: int = 40, tracing_hint: bool = True):
    if tracing_hint:
        traced = os.environ.get("LANGCHAIN_TRACING_V2") == "true"
        print(f"LangSmith tracing: {'ON — check your project in smith.langchain.com' if traced else 'off (see docstring to enable)'}")
        print()

    gateway = AIGateway()

    header = f"{'App':<26}{'Complexity':<12}{'Tier':<10}{'Cache':<7}{'Blocked':<9}{'Cost':<10}"
    print(header)
    print("-" * len(header))

    for _ in range(n_requests):
        app_id = random.choice(list(APPS.keys()))
        prompt = random.choice(SAMPLE_PROMPTS)
        result = gateway.process(app_id, prompt)
        print(
            f"{APPS[app_id]['name']:<26}{result['complexity']:<12}{result['tier']:<10}"
            f"{str(result['cache_hit']):<7}{str(result['blocked']):<9}${result['cost']:.4f}"
        )
        time.sleep(0.02)

    print(gateway.summary())


if __name__ == "__main__":
    main()
