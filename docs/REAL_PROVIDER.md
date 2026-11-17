# Running against real OpenAI models

Everything so far used the mock or a simulated provider. A real run spends real money, so do it in stages, and stop at the first surprise. The code paths below are covered by tests with a *simulated* OpenAI response; a live call has not been verified in this repository (see [VERIFICATION.md](VERIFICATION.md)).

## What the gateway does not do for you

- **It cannot cap your OpenAI bill.** Its budget is per day and per application, and it is an estimate-based reservation. OpenAI's own hard spend limit is the only real ceiling. Set it first.
- **Prices are configuration, not knowledge.** The built-in prices are fixtures. You supply `MODEL_PRICING_JSON` with a source and the date *you* checked it.
- **Reasoning tokens are billed as output.** The gateway reserves `min(MAX_OUTPUT_TOKENS, BUDGET_OUTPUT_ESTIMATE_TOKENS)` output tokens. Keep the two equal or a reply can cost more than was reserved.
- **Cached-input discounts are not modelled** (the gateway over-estimates, which is the safe direction), and OpenAI documents a higher rate above 272K input tokens. The default `MAX_PROMPT_CHARS` keeps prompts far below that.

## Stage 0: set the ceiling on OpenAI's side (before any key is used)

Follow [OPENAI_SETUP.md](OPENAI_SETUP.md): create a dedicated project, create an expiring project key, set the project's monthly **hard** spend limit and a lower alert, and check your credits. Alerts only notify; a hard limit makes requests fail with HTTP 429 (`project_spend_limit_exceeded`), and enforcement is not instantaneous. Pick a number you would shrug at for the whole trial.

## Stage 1: configure

```powershell
copy .env .env.mock                         # keep your mock setup
copy .env.real-provider.example .env
notepad .env
```

Only the preflight, the one-call check and `--live` runs read this `.env`; the test suite, the MCP smoke test, the demo walkthrough and simulated runs deliberately ignore it, so keeping it in the project folder does not change their results.

Fill in exactly two things: `OPENAI_API_KEY`, and `verified_on` for each model, **after** opening OpenAI's [model catalog](https://developers.openai.com/api/docs/models) (or [pricing page](https://developers.openai.com/api/docs/pricing)) and confirming the rates match. The template was filled from the catalog on 2026-10-29: `gpt-6.1-sol` $2/$10, `gpt-6.1-terra` $1/$5, `gpt-6-luna` $0.10/$0.50 per million input/output tokens. Treat those as a starting point.

The trial policy (`config/policies.real-provider.example.json`) lets `demo-app` use only the cheapest model, with a $0.50 daily limit.

## Stage 2: preflight (offline, spends nothing)

```powershell
python scripts/preflight_real_provider.py
```

It fails on placeholder or stale prices, an unpriced or unlisted model, an unlimited budget, an output estimate smaller than the output cap, and mock/real mixing. It prints the worst-case cost per request and how many requests the daily budget allows. It cannot check the OpenAI dashboard items; tick those yourself.

## Stage 3: one real request

```powershell
python scripts/live_gateway_check.py --confirm
```

Expect `provider=openai`, a tiny token count and a cost of a small fraction of a cent. If the reply is empty or cut off, a reasoning model likely used the output cap on thinking (an OpenAI error such as a spend limit or an invalid key is explained in plain words instead): raise `MAX_OUTPUT_TOKENS` **and** `BUDGET_OUTPUT_ESTIMATE_TOKENS` together, re-run the preflight, and retry.

## Stage 4: a small batch, then reconcile

Run the API (`uvicorn app.main:app`, local only) and send about ten requests from `http://127.0.0.1:8000/docs`. Compare the token totals in `GET /v1/usage/recent` with the OpenAI usage page for the project (it may lag). If they disagree by more than rounding, stop and find out why before widening anything.

## Stage 5: widen carefully

Add `gpt-6.1-terra` and `gpt-6.1-sol` to the application's `allowed_models`, raise the daily budget in small steps, and re-run the preflight each time. Re-verify prices whenever `verified_on` gets old; the preflight refuses dates older than 30 days.

## Kill switch and rollback

- Revoke the project key in the OpenAI dashboard (instant and certain), or lower the project's hard limit.
- Stop `uvicorn`. To go back to the mock: `copy .env.mock .env`.
- The trial uses its own database (`gateway-real.db`), so its records never mix with mock data.

## Before this is anything more than a trial

Turn on authentication and put real identity in front of it, move to PostgreSQL/Redis, and complete the items in [HARDENING.md](HARDENING.md). The trial configuration disables authentication and is for localhost only.
