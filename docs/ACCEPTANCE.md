# Acceptance test: can an existing application adopt this gateway?

The claim to test:

> **An existing application can use this gateway by changing only the function that calls its LLM provider. The gateway enforces policy before any model is called, spends only what the budget allows, and its usage records match what the application observed.**

`scripts/acceptance_check.py` tests that claim. It is a plain HTTP client (standard library only, no imports from `app/`), so it uses the gateway exactly as any other application would. Every check ends **PASS**, **FAIL** or **SKIP**. SKIP means *not proven*. The verdict is **ACCEPTED** only if nothing failed and every required check passed.

## What a PASS proves, and what it does not

| It proves | It does not prove |
|---|---|
| The documented `POST /v1/chat` contract works for a client that knows nothing about the gateway's internals | That **your** application's behaviour is unchanged. The steps in Part 3 cover that. |
| Unregistered applications, secrets, prompt injection, unavailable capabilities and oversize prompts are blocked **before** any model is called | That the injection filter catches every attack. It is heuristic; see the xfails in `docs/VERIFICATION.md`. |
| Blocked requests consume no tokens and cost nothing | Behaviour under load, or with PostgreSQL / Redis / multiple workers |
| The gateway's ledger matches, request by request, the tokens and cost the application saw | That OpenAI billed the same amount. Compare the OpenAI dashboard yourself (Part 2, step 6). |
| Identical requests are served from cache at zero cost; session history is kept and can be deleted | JWT / identity-provider integration (the default config has authentication off) |
| The daily budget stops spending (optional check E1) | Live provider calls beyond the ones you run in Part 2 |

## Part 1: dry run on the mock provider (free, about 2 minutes)

This proves your setup and the test itself. Nothing is billed.

1. Start the gateway with the default `.env` (terminal 1):
   ```powershell
   uvicorn app.main:app
   ```
2. In a second terminal with the venv active:
   ```powershell
   python scripts/acceptance_check.py --url http://127.0.0.1:8000 --expect-provider mock --report acceptance-mock.json
   ```
3. **Pass criteria:** the last line starts with `ACCEPTED`, there are no `[FAIL]` lines, and exactly one check is reported as not proven. That one is E1 (the budget stop), which needs a priced provider. Exit code is 0.

## Part 2: acceptance against the real provider

Do this only after the trial setup in `docs/REAL_PROVIDER.md` Stages 0 to 3 (hard spend limit set, preflight passing, one live call succeeded).

1. Stop the mock gateway. Start it with the real-provider `.env` (`uvicorn app.main:app`).
2. Run:
   ```powershell
   python scripts/acceptance_check.py --url http://127.0.0.1:8000 --expect-provider openai --report acceptance-real.json
   ```
3. **Pass criteria:** `ACCEPTED`, and in particular
   - **A4** shows `provider=openai`, a non-mock model, non-zero tokens and a non-zero cost
   - **D1** shows `0 mismatches` between what the application saw and what the gateway recorded
4. Optional but recommended, **E1 (budget stops spending)**. It deliberately spends one application's whole daily limit, so give it its own application with a limit of a few cents. Add to your policy file:
   ```json
   "budget-probe": { "enabled": true, "allowed_models": ["gpt-6-luna"], "required_roles": ["developer"],
                      "daily_budget_usd": 0.02, "max_requests_per_session": 1000, "max_prompt_chars": 4000,
                      "max_data_classification": "internal", "allow_pii": true }
   ```
   Set `ALLOWED_APPLICATIONS=demo-app,budget-probe`, restart, then add `--budget-app budget-probe` to the command. Expected: `N requests served ($x spent), then stopped=BUDGET_EXCEEDED`, with spend at or below the limit. The limit must exceed the cost of one request, otherwise E1 fails by design.
5. Keep `acceptance-real.json`. It is your evidence file and contains no keys.
6. **Manual reconciliation (cannot be automated):** the script prints the application-side total tokens and cost. Open the project's usage page in the OpenAI dashboard (it can lag by minutes) and compare. A difference beyond rounding means stop and investigate before relying on the gateway's numbers.

## Part 3: your actual existing application

Parts 1 and 2 use a stand-in application (`LegacyApp` in the script). To make the statement about **your** application, you must test your application.

1. **Register it.** Add its `application_id` to `ALLOWED_APPLICATIONS` and give it an entry in the policy file (allowed models, daily budget, data classification). An unregistered application is blocked by design.
2. **Find the one function that calls the LLM provider** and replace only its body. Everything else in the application stays as it is. Adapter:
   ```python
   import requests   # or any HTTP client

   GATEWAY, APP_ID = "http://127.0.0.1:8000", "your-app-id"

   class GatewayBlocked(Exception): ...

   def call_llm(prompt, session_id, user_id):
       r = requests.post(f"{GATEWAY}/v1/chat", timeout=90, json={
           "session_id": session_id, "application_id": APP_ID, "user_id": user_id, "prompt": prompt})
       r.raise_for_status()
       body = r.json()
       if body["governance"]["decision"] != "ALLOW":      # blocks arrive as HTTP 200
           raise GatewayBlocked(body["governance"]["reason"])
       return body["response"]
   ```
   Two details matter: a policy block is **HTTP 200 with `governance.decision == "BLOCK"`**, so check that field and not only the status code; and keep the gateway URL (and any JWT) in server-side configuration.
3. **Run your application's own test suite and golden prompts through the adapter.** Pass criteria:
   - every test that passed before still passes, with no changes outside the adapter function
   - return types and shapes are unchanged
   - your application handles `GatewayBlocked` (shows an error, retries, or falls back) instead of crashing
   - answers are acceptable for your use case. Model output differs from your previous provider, so judge quality yourself.
4. **Run the acceptance script with your application's ID:**
   ```powershell
   python scripts/acceptance_check.py --app your-app-id --expect-provider openai --report acceptance-your-app.json
   ```
5. Tally your results:

   | Evidence | Where it comes from |
   |---|---|
   | Gateway contract, policy, accounting | `acceptance-real.json`, verdict ACCEPTED |
   | Your app works through the adapter | Your own test suite, unchanged except the adapter |
   | Costs reconcile with the provider | OpenAI dashboard comparison (Part 2, step 6) |

## The statement you can make when everything above passes

> On *(date)*, application *(name)* was connected to the gateway by replacing only its LLM call function. Its existing tests passed unchanged. The gateway acceptance test passed against *(provider, model)* with *(n)* checks, including policy blocking before model calls and request-level reconciliation of tokens and cost with *(dashboard comparison)*. Evidence: `acceptance-real.json`.

Do not extend it to claims this procedure did not test: production readiness, concurrency or load, PostgreSQL / Redis behaviour, real identity-provider integration, or protection against every prompt-injection attack. The first two are listed under "Not verified" in `docs/VERIFICATION.md`.

## Troubleshooting

| Result | Likely cause |
|---|---|
| A1 / A2 fail | Gateway not running, wrong `--url`, or the database is unreachable |
| A3 fails with missing fields | The response contract changed; compare with `docs/INTEGRATION.md` |
| A4 fails on `mock` vs `openai` | The wrong `.env` is loaded; check `/ready` and restart |
| C1 fails | The gateway accepted an application that is not registered (check uses a made-up ID): `ALLOWED_APPLICATIONS` is too broad |
| B3 fails | Cache disabled (`CACHE_ENABLED=false`) or disabled for that application in its policy |
| D1 SKIP | Authentication is on; pass `--operator-token` with an operator JWT |
| E1 fails with 0 requests served | The budget limit is below the cost of one request; raise it |
