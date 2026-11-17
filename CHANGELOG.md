# Changelog

Test results are deliberately not quoted here. They live in [docs/VERIFICATION.md](docs/VERIFICATION.md), the single source of truth.

## Unreleased - test isolation and model-configuration consistency

- Classifier: `required_capabilities` is now checked against a capability allowlist (`VALID_CAPABILITIES`), not task names, so `vision`, `embeddings` and `tool_calling` are no longer discarded.
- New `app/routing/profiles.py`: one shared `build_model_profiles()` (moved out of the graph, behaviour unchanged) and `validate_model_configuration()`, which reports models permitted by policy but unavailable to the router (and the reverse). `build_gateway_graph` logs findings; in production it refuses to start on errors (`strict_model_config` overrides).
- Tests: `tests/conftest.py` now removes every environment variable `Settings`/pricing read, not just the `.env` file. New `tests/support.py` pins settings, declares GPT profiles explicitly and writes isolated, profile-aligned policy files; the failover fixture and economics harness both use it. Regression tests cover hostile environments and the validator.
- Failover accounting is now tested end to end against the real reservation store (`tests/test_failover_accounting.py`): the answering model is settled and recorded, failed attempts leave no active reservation, and unaffordable or unpriced candidates are skipped. The economics harness gained a `failing` option for this. No gateway defect was found in this area.
- Acceptance test: `scripts/acceptance_check.py` (standard-library HTTP client, no gateway imports) checks that an existing application can adopt the gateway through its REST contract, that policy blocks happen before any model call, and that the gateway's ledger matches what the application observed. It is itself tested against a healthy and three deliberately weakened gateways. Procedure and limits: `docs/ACCEPTANCE.md`.
- Docs: capability vocabulary (`INTEGRATION.md`), policy/profile consistency (`HARDENING.md`), test hermeticity (`README.md`); `VERIFICATION.md` updated with new figures and narrower claims (only Python 3.12 re-run).



## v6.10 — tests and demos no longer read your private `.env`
- Fixed: the test suite read the project's `.env` automatically. With a real-provider `.env` in the folder (as created in the real-OpenAI walkthrough), dozens of tests failed because the allowed applications, models, prompt limit and budgets came from the real configuration. `.env` is now loaded through `app/envfile.py`; `tests/conftest.py` sets `GATEWAY_IGNORE_DOTENV=1`, so tests never depend on it. The MCP smoke test, the demo walkthrough and the simulated showcase set the same flag. The preflight, the one-call check and `--live` runs still read `.env` on purpose, and an explicit `--env-file` is always honoured.
- Added `tests/test_dotenv_isolation.py` and `requirements.lock.txt` (known-good versions, resolvable on Python 3.12 and 3.14).

## v6.9 — simulated runs ignore a real-provider .env
- Fixed: `scripts/run_showcase.py` in simulated mode inherited `BASELINE_MODEL`, token caps and prices from a real-provider `.env`, which priced the baseline at real rates against fixture-priced traffic and produced negative “savings”. Simulated runs now pin their own baseline, caps and prices. Live mode still uses your `.env` on purpose. Regression test added.

## v6.8 — Windows-safe test environments
- The subprocess tests added between v6.4 and v6.6 handed child Python processes a stripped-down environment. On Windows, Python needs `SYSTEMROOT` and a few other variables to start, so those tests could fail there for reasons unrelated to the code. They now go through one helper that keeps the required system variables.

## v6.7 — presenter guide
- Fixed a time-bomb test inherited from the original package: `tests/test_production_configuration.py` hard-coded a pricing `verified_on` date, and the repo correctly rejects pricing older than 30 days, so the test began failing once the calendar passed that window. It now uses today's date. Re-ran every in-process test with the clock moved months ahead to confirm no other test depends on a fixed date.
- Added `docs/PRESENTING.md`: a 10-minute talk track keyed to the dashboard sections, a can-say/do-not-say table, and answers to the likely leadership questions, including the integration gaps (HS256-only JWT, no SIEM/OpenTelemetry export, unverified PostgreSQL/Redis).

## v6.6 — dashboard for a real OpenAI run
- `scripts/run_showcase.py --live --confirm-spend --max-usd N` runs the scripted scenario through real OpenAI using your `.env`: it runs the preflight, refuses when the computed worst-case spend exceeds the cap, stops at the first provider failure, and records the preflight result and worst-case bound in the run data.
- The dashboard gained a data-driven source badge, a “Four layers keep spend bounded” panel, a reconcile-with-OpenAI panel, and a proof check that actual spend stayed under the pre-run worst case. Simulated runs show “Simulated model provider”; live runs show “Real OpenAI provider”.
- Tests cover each live-mode refusal and an end-to-end live run with a simulated OpenAI reply.

## v6.4 — safe path to real OpenAI calls
- Added `docs/REAL_PROVIDER.md`, `.env.real-provider.example` (current GPT-6 model IDs and rates from OpenAI's model catalog, with the verification date left for the user) and `config/policies.real-provider.example.json` (cheapest model only, small daily budget).
- Added `scripts/preflight_real_provider.py`, an offline check that fails on placeholder or stale prices, unpriced models, unlimited budgets, an output estimate below the output cap, and mock/real mixing; and `scripts/live_gateway_check.py`, a single real request that refuses to run without `--confirm` or with a failing preflight.
- Added `docs/OPENAI_SETUP.md` (dashboard walkthrough for projects, expiring keys, hard spend limits, credits, error codes). The preflight now lists the exact OpenAI screens, and the one-call check translates OpenAI's error codes (spend limit, credits, usage limit, 401/403/404/429) into plain advice.
- Added `tests/test_real_provider_safety.py`: every hazard above is injected and must be caught, and the GPT-6 configuration is run end to end through the gateway with a simulated OpenAI response.

## v6.3 — leadership dashboard on real data
- Added `showcase/ai-gateway-showcase.html`, a self-contained dashboard built from a real gateway run: live proof panel, spend, routing, budget and block charts, and a per-request inspector over the audit trail. Replaces simulated-data dashboards as the demo to present; see [docs/SHOWCASE.md](docs/SHOWCASE.md).
- Added `scripts/run_showcase.py` (scripted traffic through the real API with a simulated provider), `scripts/build_showcase.py` and `tests/test_showcase.py`.

## v6.1 — fixes found by the first full test run and a live stdio MCP session

**Gateway**
- **Budget reservations now settle.** `budget_reservation_id` was missing from `GatewayState`, so LangGraph dropped it between nodes and the execute step could not settle or release the reservation. Reservations stayed locked until lease expiry (default 15 minutes) and spend was only visible through the usage ledger. Added the key and a regression test.
- **Admission can no longer be more permissive than the reported budget.** `status()` used `max(budget row, ledger)` while `reserve()` checked only the budget row. `reserve()` now reconciles against the ledger in the same transaction.

**MCP adapter**
- **Operator role is enforced.** `gateway_get_routing_decision` and `gateway_get_usage` now require `operator` or `admin`, matching the REST control-plane endpoints. `require_mcp_operator` was previously imported but never called.
- **Local dev identity is least-privilege.** It is a plain `developer` unless `MCP_DEV_ROLES` says otherwise.
- **stdout is reserved for the protocol.** Structured logs went to stdout, corrupting the JSON-RPC stream for any real client. The server now sets `LOG_STREAM=stderr`; `configure_logging()` honours it.
- **The documented token setup works.** `MCP_GATEWAY_BEARER_TOKEN` accepts the bare JWT as the docs say (it previously required a `Bearer ` prefix).
- Replaced the `__import__(...)` workaround with normal imports.

**Tests and tooling**
- The economics test harness used the shared `./gateway.db`, leaking reservations between tests and runs. Each test now gets its own database.
- Added `scripts/mcp_smoke_test.py` (live stdio client; local and JWT modes), `tests/test_mcp_stdio_smoke.py`, `tests/test_mcp_operator.py`, static contract tests, and `tests/test_docs.py` (broken links, stale test counts).
- Added `scripts/demo_mcp_walkthrough.py` and a recorded replay under `demo/`.

**Docs**
- Consolidated into `docs/` with one verification page; removed `VALIDATION_REPORT.md` and `VERIFICATION_REPORT.md`, whose content is folded into [docs/VERIFICATION.md](docs/VERIFICATION.md) and this changelog.

## v6 — MCP integration
- Added `app/mcp_server.py`, a stdio MCP adapter over the canonical gateway with six tools (`gateway_chat`, `gateway_estimate_cost`, `gateway_check_budget`, `gateway_get_routing_decision`, `gateway_get_usage`, `gateway_health`), JWT/application-scope checks in `app/mcp_auth.py`, and a deliberately disabled remote transport. See [docs/MCP.md](docs/MCP.md).

## v4 — enterprise hardening
- Atomic SQL budget reservations using a conditional database update, shared across workers on the same PostgreSQL database; idempotent reservation IDs, expiry/reaping, release on provider failure, reconciliation against actual provider usage.
- Failover starts with the governance-approved model and reserves the fallback candidate before calling it.
- The OpenAI adapter rejects missing usage metadata and invalid token counts; the gateway checks that the returned model matches the requested model.
- Production configuration fails closed for disabled auth, weak or placeholder JWT secrets, placeholder API keys, model IDs or issuer values, mock providers, non-PostgreSQL storage, non-shared rate limiting, missing, stale or invalid pricing metadata, and inconsistent model profiles.
- Shared Redis rate limits, cache and provider circuit state in production; SQL-backed sessions, audit, usage and budget records.
- Request-correlated structured logs, response timing/request ID headers, readiness checks, non-root container and restricted Docker Compose deployment.
- CI workflow, provider pricing metadata validation helper, cross-worker and idempotency tests.
- Routing audit: every completed or governance-blocked chat stores a structured routing decision (classification, candidates, reason, estimated cost, reservation ID, executed model, failover history, cache status), with a backwards-compatible migration.

## Unification — one canonical runtime
- `app/` is the single supported FastAPI + LangGraph runtime. The standalone `code/` gateway and its duplicate scripts moved to `archive/legacy_http_gateway/` for reference only; integration docs now target `POST /v1/chat`.
- Added `app/routing/classifier.py` (transparent task/priority inference and allowlisted client hints) and an optional `routing` field on the chat request.
- Candidates are filtered by application policy, ranked once, and the ranked list is persisted in graph state; the approved first choice is executed and failover is limited to that list, with each fallback checked against the budget.
- Cost-priority scoring uses a weighted input/output price estimate. For budgeted requests, real models with unknown pricing are blocked rather than treated as free; unknown-price usage is marked unpriced and no baseline savings are invented for it.
