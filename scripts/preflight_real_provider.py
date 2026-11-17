"""Offline preflight for a real-provider run. Makes NO network calls and spends nothing.

    python scripts/preflight_real_provider.py [--env-file PATH]

Exit 0 only when no FAIL remains. It checks the configuration mistakes that turn a trial into a surprise bill:
fixture or stale prices, unlimited budgets, an output estimate smaller than the output cap, mock/real mixing.
"""
import argparse, json, math, os, sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.envfile import load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OPENAI_PRICING = "https://developers.openai.com/api/docs/pricing"


def run(env_file=None):
    load_env(env_file, default=ROOT / ".env")
    e = lambda k, d="": os.getenv(k, d).strip()
    out = []
    add = lambda lvl, msg: out.append((lvl, msg))

    key = e("OPENAI_API_KEY")
    if not key or key.startswith("REPLACE"):
        add("FAIL", "OPENAI_API_KEY is empty or still a placeholder.")
    else:
        add("OK", f"OPENAI_API_KEY is set ({len(key)} characters; never printed)." + ("" if key.startswith("sk-") else " WARN: it does not start with sk-."))
    if e("MOCK_PROVIDER_ENABLED", "true").lower() != "false":
        add("FAIL", "MOCK_PROVIDER_ENABLED must be false, otherwise mock traffic mixes into a real run.")

    allowed = [m.strip() for m in e("ALLOWED_MODELS").split(",") if m.strip() and m.strip() != "mock-general"]
    try:
        pricing = json.loads(e("MODEL_PRICING_JSON") or "{}")
    except ValueError as exc:
        pricing = {}; add("FAIL", f"MODEL_PRICING_JSON is not valid JSON: {exc}")
    try:
        profiles = json.loads(e("MODEL_PROFILES_JSON") or "[]")
    except ValueError as exc:
        profiles = []; add("FAIL", f"MODEL_PROFILES_JSON is not valid JSON: {exc}")
    if not allowed:
        add("FAIL", "ALLOWED_MODELS is empty.")
    if not profiles:
        add("FAIL", "MODEL_PROFILES_JSON is empty: the built-in default profiles use fixture model names, not your real models.")
    today, max_age = date.today(), int(e("PRICING_MAX_AGE_DAYS", "30"))
    for m in allowed:
        p = pricing.get(m)
        if not isinstance(p, dict):
            add("FAIL", f"{m}: no entry in MODEL_PRICING_JSON, so it cannot be budgeted."); continue
        try:
            ok_price = float(p["input_per_1m"]) > 0 and float(p["output_per_1m"]) > 0
        except (KeyError, ValueError, TypeError):
            ok_price = False
        if not ok_price:
            add("FAIL", f"{m}: input_per_1m and output_per_1m must be positive numbers.")
        if not p.get("source"):
            add("FAIL", f"{m}: pricing entry needs a source URL.")
        try:
            age = (today - datetime.strptime(str(p.get("verified_on")), "%Y-%m-%d").date()).days
            if age < -1:
                add("FAIL", f"{m}: verified_on is in the future.")
            elif age > max_age:
                add("FAIL", f"{m}: prices were verified {age} days ago (limit {max_age}). Re-check {OPENAI_PRICING}.")
            else:
                add("OK", f"{m}: priced {p['input_per_1m']}/{p['output_per_1m']} per 1M tokens, verified {age} day(s) ago.")
        except ValueError:
            add("FAIL", f"{m}: verified_on must be the date YOU checked the price, as YYYY-MM-DD.")
    if e("BASELINE_MODEL") not in pricing:
        add("FAIL", "BASELINE_MODEL needs an entry in MODEL_PRICING_JSON.")
    for pr in profiles:
        if pr.get("provider") == "openai" and pr.get("model") not in allowed:
            add("FAIL", f"Profile {pr.get('model')} is not in ALLOWED_MODELS.")

    cap, est = int(e("MAX_OUTPUT_TOKENS", "2000")), int(e("BUDGET_OUTPUT_ESTIMATE_TOKENS", "500"))
    if est < cap:
        add("FAIL", f"BUDGET_OUTPUT_ESTIMATE_TOKENS ({est}) < MAX_OUTPUT_TOKENS ({cap}): the gateway could reserve {cap / est:.1f}x less than a reply can cost. Set them equal.")
    else:
        add("OK", f"Reservation covers the full output cap ({cap} tokens).")
    if cap > 2000:
        add("WARN", f"MAX_OUTPUT_TOKENS={cap} is high for a first run. Reasoning tokens are billed as output.")
    prompt_tokens = math.ceil(int(e("MAX_PROMPT_CHARS", "20000")) / 3)
    if prompt_tokens > 272_000:
        add("WARN", "Prompts could exceed 272K tokens, where OpenAI documents a higher long-context rate that this gateway does not price.")

    policy_path = Path(e("POLICY_FILE", "config/policies.json"))
    policy_path = policy_path if policy_path.is_absolute() else ROOT / policy_path
    try:
        apps = json.loads(policy_path.read_text(encoding="utf-8"))["applications"]
    except (OSError, ValueError, KeyError) as exc:
        apps = {}; add("FAIL", f"Cannot read policy file {policy_path}: {exc}")
    for name, c in apps.items():
        if not c.get("enabled", True):
            continue
        if not float(c.get("daily_budget_usd", 0)) > 0:
            add("FAIL", f"{name}: daily_budget_usd is 0, which means UNLIMITED. Set a limit."); continue
        stray = [m for m in c.get("allowed_models", []) if m not in allowed]
        if stray:
            add("FAIL", f"{name}: allows models outside ALLOWED_MODELS: {', '.join(stray)}")
        worst = {m: prompt_tokens * float(pricing[m]["input_per_1m"]) / 1e6 + cap * float(pricing[m]["output_per_1m"]) / 1e6
                 for m in c.get("allowed_models", []) if m in pricing and isinstance(pricing[m], dict) and pricing[m].get("input_per_1m")}
        if worst:
            top = max(worst, key=worst.get)
            add("OK", f"{name}: budget ${c['daily_budget_usd']}/day; worst case per request ${worst[top]:.5f} ({top}), about {int(c['daily_budget_usd'] / worst[top])} requests before the gateway stops it.")
    extra = set(a.strip() for a in e("ALLOWED_APPLICATIONS").split(",") if a.strip()) - set(apps)
    if extra:
        add("WARN", f"ALLOWED_APPLICATIONS names apps with no policy: {', '.join(sorted(extra))}")
    if e("AUTH_ENABLED", "false").lower() != "true":
        add("WARN", "AUTH_ENABLED=false: acceptable only on localhost. Never expose this configuration.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--env-file", default=None)
    results = run(ap.parse_args(argv).env_file)
    for lvl, msg in results:
        print(f"[{lvl:<4}] {msg}")
    fails = sum(1 for l, _ in results if l == "FAIL")
    print("\nCannot be checked from here. Do these in the OpenAI dashboard first (details: docs/OPENAI_SETUP.md):")
    for t in ("Project selector > Create project (a dedicated trial project, not your Default project).",
              "Organization settings > select that project > API Keys > + Create new secret key, with an expiration date.",
              "Project settings > Limits > Spend > Edit spend limit: set a Monthly spend limit and turn on Enforce a hard limit.",
              "Add a spend alert below the limit (alerts only notify; they never stop traffic).",
              "Billing: if your account uses prepaid credits, load only a small amount.",
              f"Open {OPENAI_PRICING} and confirm every rate before setting verified_on to today."):
        print(f"  [ ] {t}")
    print(f"\n{'PREFLIGHT FAILED: ' + str(fails) + ' problem(s). Nothing was sent anywhere.' if fails else 'Preflight passed. No network call was made.'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
