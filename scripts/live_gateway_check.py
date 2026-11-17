"""ONE real request through the gateway. This spends real money (a fraction of a cent).

    python scripts/live_gateway_check.py --confirm [--app demo-app]

Refuses to run without --confirm or when the offline preflight fails. Prints what OpenAI reported
(tokens) and what the gateway recorded (cost), so you can compare it with the OpenAI usage dashboard.
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))


DASH = "https://platform.openai.com/settings/organization"
DIAGNOSES = [  # (text to look for, advice). Codes from OpenAI's spend-limits guide; statuses are standard HTTP.
    ("project_spend_limit_exceeded", "Your OpenAI PROJECT hard spend limit is reached. That is your safety net working. Raise it under Project settings > Limits > Spend only if you mean to continue."),
    ("organization_spend_limit_exceeded", f"Your OpenAI ORGANIZATION hard spend limit is reached. Review it at {DASH}/limits."),
    ("organization_usage_limit_exceeded", f"OpenAI's approved usage limit for your organization is reached. Request a higher one at {DASH}/limits."),
    ("credit_balance_exhausted", f"Prepaid credits are used up. Add credits at {DASH}/billing."),
    ("Error code: 401", "OpenAI rejected the key: wrong, revoked or expired. Create a new key in the project and update OPENAI_API_KEY."),
    ("Error code: 403", "The key or project is not permitted to do this: check the key's permissions (Restricted keys need model access) and the project's model access."),
    ("Error code: 404", "OpenAI does not know that model ID for this project. Compare ALLOWED_MODELS with https://developers.openai.com/api/docs/models."),
    ("Error code: 429", "OpenAI is rate limiting this key. Wait a minute and retry; see https://developers.openai.com/api/docs/guides/rate-limits."),
    ("PROVIDER_USAGE_MISSING", "OpenAI's reply carried no token usage, so the gateway refused to price it."),
    ("PROVIDER_MODEL_MISMATCH", "OpenAI answered with a different model than requested; the gateway refused to bill it."),
    ("imeout", "The request timed out (REQUEST_TIMEOUT_SECONDS). Check connectivity or raise the timeout."),
]


SPECIFIC = 4   # the first four entries are exact OpenAI error codes; if one matches, skip the generic status hints


def diagnose(text):
    text = text or ""
    for needle, advice in DIAGNOSES[:SPECIFIC]:
        if needle in text:
            return [advice]
    return [advice for needle, advice in DIAGNOSES[SPECIFIC:] if needle in text]


def main(argv=None, provider_factory=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true"); ap.add_argument("--app", default="demo-app")
    a = ap.parse_args(argv)
    if not a.confirm:
        print("Refusing to run: this makes a REAL, billable request. Re-run with --confirm."); return 2
    import preflight_real_provider as pre
    if pre.main([]) != 0:
        print("Not sending anything: fix the preflight failures first."); return 3
    from fastapi.testclient import TestClient
    import app.gateway.graph as graph_mod
    if provider_factory:                                  # test hook only
        graph_mod.get_provider = provider_factory
    from app.main import app
    try:
        r = TestClient(app).post("/v1/chat", json={"session_id": "live-check", "application_id": a.app, "user_id": "live-check",
                                                  "prompt": "Reply with the single word: OK", "routing": {"task_type": "general_fast", "priority": "cost"}})
    except Exception as exc:                              # the gateway raises ALL_MODELS_FAILED: <OpenAI's error>
        print(f"\nThe request failed: {str(exc)[:400]}")
        for line in diagnose(str(exc)) or ["No known OpenAI error code found. Read the message above."]:
            print("  ->", line)
        print("\nNothing further was sent.")
        return 1
    b = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    gov, u = b.get("governance", {}), b.get("usage", {})
    print(f"\nHTTP {r.status_code} | decision={gov.get('decision')} reason={gov.get('reason')}")
    print(f"provider={b.get('provider')} model={b.get('model')}")
    print(f"tokens reported by the provider: in={u.get('input_tokens')} out={u.get('output_tokens')} total={u.get('total_tokens')}")
    print(f"cost recorded by the gateway: ${(b.get('economics') or {}).get('cost_usd')}   budget: {b.get('budget')}")
    print("reply:", (b.get("response") or "")[:200])
    ok = r.status_code == 200 and gov.get("decision") == "ALLOW" and b.get("provider") == "openai" and bool(u.get("total_tokens"))
    for line in ([] if r.status_code == 200 and gov.get("decision") == "ALLOW" else diagnose(r.text)):
        print("  ->", line)
    print("\n" + ("Real call succeeded. Compare these tokens with the OpenAI usage page for your project." if ok else "Not a successful real call. Read the lines above; nothing further was sent."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
