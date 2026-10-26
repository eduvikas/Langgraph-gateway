# Verification status

This is the **only** document that quotes test results. Everything else links here, so numbers cannot drift apart. `tests/test_docs.py` fails if a count appears elsewhere.

**Verdict:** an enterprise-oriented reference implementation that is tested end to end against SQLite and the mock provider. It is **not** production-certified.

## Verified (v6.1)

Environment: Python 3.12, SQLite, mock provider, no network access to any model provider.

| Check | Command | Result |
|---|---|---|
| Full test suite | `python -m pytest -q` | 444 passed, 1 skipped, 17 xfailed |
| Stable under reuse and reordering | same, repeated on a used database and with `pytest-randomly` | same result each time |
| Live MCP session over stdio (real client SDK) | `python scripts/mcp_smoke_test.py` | 27 of 27 checks passed |

| Leadership dashboard fidelity | `tests/test_showcase.py` (part of the suite) | page data equals the run data, run data reconciles, page loads no external resources |

The dashboard page was also executed once in a headless DOM (jsdom): no script errors, all six proof checks passed, filters and the request inspector worked. It has **not** been viewed in a real browser or on a phone, so layout is unchecked.

What the smoke test covers, by driving the real server as a subprocess:
- **Local identity mode:** discovery of all six tools, `gateway_chat`, cost estimate, budget, health, governance block of an unknown application, input validation, operator-only tools denied to a developer and allowed to an operator, application-scoped audit lookups.
- **JWT mode (real HS256 tokens, `AUTH_ENABLED=true`):** identity taken from the token, bare and `Bearer`-prefixed tokens, role enforcement, application scope, admin wildcard scope, and rejection of forged, expired and missing tokens.

The 17 xfails are documented misses and false positives of the prompt-injection heuristics (`tests/test_injection_corpus.py`). They are marked expected-failure so the limit stays visible rather than hidden. The 1 skip is the opt-in live-provider test.

Regression guards were checked by temporarily reverting the fixes: removing the state-schema key, the operator check, the token normalisation or the stderr logging each makes at least one test fail.

## Not verified

- Real OpenAI calls (the live-provider test is opt-in and costs money): `RUN_LIVE_PROVIDER_TESTS=1 pytest -q tests/test_live_openai_smoke.py`.
- PostgreSQL and Redis integration; multi-worker concurrency and load.
- Docker image build and the production Compose deployment.
- Current provider prices. `scripts/verify_provider_pricing.py` only checks local metadata format and freshness; a person must check the official source.
- Visual layout of the dashboard on real browsers and devices.
- Remote (Streamable HTTP) MCP transport. It is refused by design.
- Routing and the heuristic classifier against a representative enterprise workload, and quality, latency and cost against a real baseline.
- Dollar figures from the mock provider are demonstrations of the mechanics, not measured savings.

## Reproduce

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m compileall -q app tests scripts
python -m pytest -q
python scripts/mcp_smoke_test.py
```

## History

Earlier reports quoted different figures because they measured different things:

| Stage | What was run | Result |
|---|---|---|
| v4 packaging (`langgraph` not installable) | 8 selected modules only | 308 passed, 1 skipped, 17 xfailed. The full suite could not be collected. |
| v6.1, first full run | everything, dependencies installed | 417 passed, 4 failed. Two of the failures were test-isolation problems, and the budget failures exposed the unsettled-reservation bug fixed in v6.1 (see [CHANGELOG](../CHANGELOG.md)). |
| v6.1, after fixes | everything | the figures in the table above |
