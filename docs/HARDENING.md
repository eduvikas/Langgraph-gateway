# Enterprise hardening

This release is a hardened prototype, not a certification of production readiness. The implementation changes below are present in source; live-provider and deployment validation must be completed in the target environment. What has and has not been tested is recorded in [VERIFICATION.md](VERIFICATION.md).

## Implemented in this release

- **Cross-worker budget reservations:** `app/economics/reservations.py` stores daily spend and active reservations in the shared SQL database. Admission uses a conditional atomic `UPDATE`, so simultaneous requests cannot all reserve against the same remaining amount. Reservations are idempotent by request ID, expire after 15 minutes to recover from crashed workers, and reconcile estimated reservations against provider-reported actual cost.
- **Failover-aware reservations:** the gateway releases a failed model's reservation before reserving the next eligible candidate. It attempts the model selected during governance first and does not rerank the list during execution.
- **Usage validation:** the OpenAI adapter rejects responses with missing/invalid usage; model mismatch and malformed token counts fail closed. Actual usage is used for cost accounting.
- **Pricing provenance:** `MODEL_PRICING_JSON` supports per-model input/output rates, a HTTPS source and verification date. Production startup rejects missing pricing, placeholder sources, invalid dates, zero-price non-mock models, and an unpriced baseline. Built-in rates are demo fixtures only and must not be represented as verified current prices.
- **Production startup checks:** production requires JWT authentication, a non-default 32+ character secret, issuer/audience, PostgreSQL, Redis-backed rate limiting, shared SQL sessions, Redis cache when enabled, no mock provider, and explicit model profiles/prices.
- **Shared state:** SQL stores sessions, audit, usage and budget reservations; Redis backs distributed rate limits, cache and provider health/circuit state in production.
- **Observability:** JSON logs include request ID, method, path, status and duration. Responses return `X-Request-ID` and `X-Response-Time-Ms`; readiness checks verify database connectivity and configured Redis connectivity.
- **Deployment hardening:** non-root Docker image, read-only root filesystem, dropped Linux capabilities, no-new-privileges, private service network, PostgreSQL/Redis health checks and no published database/cache ports.

## Important limits

- Budget reservations are based on a preflight estimate. They prevent concurrent requests from all consuming the same estimated remaining budget, but cannot guarantee a strict dollar ceiling if actual provider usage exceeds the estimate after the provider has already executed. Set conservative output reservations and reconcile actual costs.
- Expired reservations are reclaimed when the same application's budget status/reservation is next accessed. For high-volume systems, consider a scheduled cleanup task and alert on old active reservations.
- Redis and PostgreSQL availability, TLS, backup/restore, secret-manager integration, network policy, identity-provider key rotation and load behaviour need validation in the target environment.
- Current model IDs and rates in the local demo are examples. Production must configure provider-supported model IDs and current official price references; do not assume demo rates are accurate.
- Live provider smoke tests are opt-in because they incur API charges.

## Running the tests (Windows / Python venv)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m compileall -q app tests
pytest -q
```

The complete suite needs everything in `requirements.txt`, including LangGraph and the `mcp` SDK. If network access is restricted, install approved dependencies through your organization's package mirror. Do not skip the suite and claim end-to-end validation.

Focused tests for atomic reservations, production config and pricing safety:

```powershell
pytest -q tests/test_budget_reservations.py tests/test_production_configuration.py tests/test_pricing_safety_unit.py tests/test_request_classifier.py
```

## Live provider test

Set `OPENAI_API_KEY`, `OPENAI_MODEL` to a provider-supported model, and `RUN_LIVE_PROVIDER_TESTS=1`, then run:

```powershell
pytest -q tests/test_live_openai_smoke.py
```

This sends a real request and can incur API charges. It validates that the provider returns usage metadata; pricing values still need to be checked against the official pricing source listed in `MODEL_PRICING_JSON`.

## Production configuration and deployment

1. Copy `.env.production.example` to `.env` and replace every `REPLACE_...` value. Generate strong passwords/secrets through your approved secret manager. Keep `.env` out of source control.
2. Replace placeholder model IDs with provider-supported IDs. Configure `MODEL_PROFILES_JSON`, `ALLOWED_MODELS`, `BASELINE_MODEL`, and `MODEL_PRICING_JSON` consistently. Use the official HTTPS pricing page and record the date it was checked.
3. Validate production configuration locally by loading the settings and calling `validate_production_settings` (startup also enforces it).
4. From the repository root, run `docker compose --env-file .env -f deploy/docker-compose.production.yml config` to review the rendered configuration, then `docker compose --env-file .env -f deploy/docker-compose.production.yml up --build` in an approved Docker environment.
5. The gateway is bound to `127.0.0.1:8000`; put it behind an approved TLS-terminating reverse proxy/API gateway with network restrictions. Do not expose PostgreSQL or Redis publicly.
6. Validate `/ready`, authentication/RBAC, model allowlists, budget concurrency, failover, logs, database backups and restore before accepting production traffic.

## Routing decision audit record

Every completed chat and governance-block event stores a structured `routing_decision` JSON payload in `gateway_security_audit`. It includes task type, priority, estimated complexity, required capabilities, initial selected provider/model, ranked candidates and scores, routing reason, estimated cost, budget reservation ID, final executed provider/model (when execution succeeds), failed models, cache status, and any block reason. `AuditStore.recent()` returns this payload as a JSON object. Existing databases are migrated on startup by adding the nullable `routing_decision` column if it is missing.

Validation: `pytest -q tests/test_routing_audit.py tests/test_budget_reservations.py` covers JSON persistence, legacy schema migration, reservation concurrency and cross-worker sharing.
