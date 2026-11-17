"""Show the token-economics features working, with no API key and no spend.

    python scripts/economics_demo.py

Sends 40 requests (10 different questions, each asked by 4 users in separate conversations) through the
real API with the mock provider priced as gpt-5.6-luna, then prints the economics report.

The percentages are a DEMONSTRATION of the mechanics, not a forecast: they come from pricing the mock as a
cheap model against an expensive baseline and from a cache hit rate this script engineers. Your real
figures depend on your traffic, your prices and how often questions repeat.
"""
import os
import sys
import tempfile

os.environ.update(OPENAI_API_KEY="", MOCK_PROVIDER_ENABLED="true", AUTH_ENABLED="false",
                  MOCK_PRICING_MODEL=os.environ.get("MOCK_PRICING_MODEL", "gpt-5.6-luna"),
                  DATABASE_URL="sqlite:///" + os.path.join(tempfile.mkdtemp(), "demo.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main():
    client = TestClient(app)
    questions = [f"Question {i}: summarise section {i} of the vendor agreement, covering obligations, fees and termination terms."
                 for i in range(10)]
    hits = 0
    for user in range(4):
        for i, q in enumerate(questions):
            r = client.post("/v1/chat", json={"session_id": f"u{user}-q{i}", "application_id": "demo-app",
                                              "user_id": f"user{user}", "prompt": q}).json()
            hits += r["cache_hit"]
    print(f"40 requests -> {hits} served from the cache\n")
    e = client.get("/v1/control-tower/economics").json()
    t, a = e["totals"], e["by_application"][0]
    print(f"requests {t['requests']}   cache hits {t['cache_hits']} ({t['cache_hit_rate']:.0%})   "
          f"tokens consumed {t['tokens']}   tokens avoided {t['tokens_avoided']}")
    print(f"spent ${t['cost_usd']:.6f}   baseline (same tokens on the baseline model) ${t['baseline_cost_usd']:.6f}")
    print(f"savings ${t['savings_usd']:.6f} = {t['savings_pct']:.1%}   "
          f"[cache ${t['savings_from_cache_usd']:.6f} | model choice ${t['savings_from_model_choice_usd']:.6f}]")
    b = a["budget"]
    print(f"{a['application_id']}: ${a['cost_usd']:.6f} spent today of a ${b['limit_usd']:.2f} budget ({b['utilization']:.2%} used)")


if __name__ == "__main__":
    main()
