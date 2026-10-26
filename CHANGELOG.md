# Changelog

Test results are deliberately not quoted here. They live in [docs/VERIFICATION.md](docs/VERIFICATION.md), the single source of truth.

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
