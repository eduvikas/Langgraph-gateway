# Verification status

This is the **only** document that quotes test results. Everything else links here, so numbers cannot drift apart. `tests/test_docs.py` fails if a count appears elsewhere.

**Verdict:** an enterprise-oriented reference implementation that is tested end to end against SQLite and the mock provider. It is **not** production-certified.

## Verified (v6.1)

Environment: Linux, Python 3.12 (the figures below were re-run on 3.12 only after the test-isolation and classifier changes; 3.14 gave the same results before them and has **not** been re-run since), SQLite, mock provider, no network access to any model provider. **Windows has not been tested by the author.** A version-pinned install is in `requirements.lock.txt`.

| Check | Command | Result |
|---|---|---|
| Full test suite | `python -m pytest -q` | 502 passed, 1 skipped, 17 xfailed (with Node.js installed). Without Node.js the dashboard script syntax check skips too: 501 passed, 2 skipped, 17 xfailed. The one skip with Node is the billable live-provider test, which needs `RUN_LIVE_PROVIDER_TESTS=1`. |
| Stable under reuse and reordering | same, repeated on a used database and with `pytest-randomly` (seeds 1 and 20260717) | same result each time |
| Live MCP session over stdio (real client SDK) | `python scripts/mcp_smoke_test.py` | 27 of 27 checks passed |

| Leadership dashboard fidelity | `tests/test_showcase.py` (part of the suite) | page data equals the run data, run data reconciles, page loads no external resources; live mode refuses without `--confirm-spend`, on a failing preflight and when the worst case exceeds the cap; an end-to-end live run with a *simulated* OpenAI reply reconciles and stays under its worst-case bound |

| Real-provider safety net | `tests/test_real_provider_safety.py` (part of the suite) | preflight fails on each injected money-risk; GPT-6 configuration runs end to end with a *simulated* OpenAI response and the recorded cost equals tokens times the configured prices; OpenAI error codes are translated into plain advice |

| Independence from a private `.env` | `tests/test_dotenv_isolation.py`; the full suite with a real-provider `.env` in the folder | all tests pass; before this was fixed, a real-provider `.env` made dozens of tests fail |
| Independence from exported environment variables | `tests/test_environment_isolation.py`; the full suite with `ALLOWED_APPLICATIONS`, `MODEL_PROFILES_JSON`, `BASELINE_MODEL`, `DEFAULT_DAILY_BUDGET_USD` and `OPENAI_API_KEY` exported | all tests pass; before `tests/conftest.py` removed them, such variables failed the failover, economics and budget tests |
| Acceptance for an existing application | `scripts/acceptance_check.py` against a running gateway (mock provider); `tests/test_acceptance_script.py` starts real servers | accepts a healthy gateway; refuses gateways with secret blocking, injection blocking or the cache switched off, and a stopped gateway; the budget stop (E1) passes only after real spending and fails when the limit is below one request. Procedure: `ACCEPTANCE.md` |
| Failover accounting | `tests/test_failover_accounting.py` (reads the reservation tables, not just `status()`) | after a failover the answering model is the one settled and recorded; failed attempts leave no active reservation; unaffordable and unpriced candidates are skipped |
| Capability routing and model-configuration consistency | `tests/test_request_classifier.py`, `tests/test_model_configuration.py` | `vision`, `embeddings` and `tool_calling` survive classification and constrain routing; policy/profile drift is reported, and refused at startup in production |

The dashboard page was also executed in a headless DOM (jsdom), for both simulated-run data and live-shaped data: no script errors, all proof checks passed, and the filters, request inspector and reconcile inputs worked. It has **not** been viewed in a real browser or on a phone, so layout is unchecked.

What the smoke test covers, by driving the real server as a subprocess:
- **Local identity mode:** discovery of all six tools, `gateway_chat`, cost estimate, budget, health, governance block of an unknown application, input validation, operator-only tools denied to a developer and allowed to an operator, application-scoped audit lookups.
- **JWT mode (real HS256 tokens, `AUTH_ENABLED=true`):** identity taken from the token, bare and `Bearer`-prefixed tokens, role enforcement, application scope, admin wildcard scope, and rejection of forged, expired and missing tokens.

The 17 xfails are documented misses and false positives of the prompt-injection heuristics (`tests/test_injection_corpus.py`). They are marked expected-failure so the limit stays visible rather than hidden. The 1 skip is the opt-in live-provider test.

Regression guards were checked by temporarily reverting the fixes: removing the state-schema key, the operator check, the token normalisation or the stderr logging each makes at least one test fail. The failover accounting tests were checked the same way: settling the estimate instead of the actual cost, skipping settlement, or removing the unpriced-model check each fails them, as does removing any two of the three places a reservation is released. Removing only one of those three is not detected, because each is covered by another (deliberate redundancy, not a gap in the tests).

## Not verified

- Capability routing against real multimodal or tool-calling models. Tests use synthetic profiles; whether a given real model actually supports a capability it is configured with is not checked.
- The model-configuration check against a real production `.env` and policy file. It is tested on synthetic and shipped-default configurations only.
- The acceptance procedure against a real provider and against your own application: only the mock provider and a stand-in application were run. Part 2 and Part 3 of `ACCEPTANCE.md` are yours to run.
- Real OpenAI calls. The preflight and the one-call check are tested only against a simulated response; nothing here has contacted OpenAI. Follow [REAL_PROVIDER.md](REAL_PROVIDER.md) (the opt-in `RUN_LIVE_PROVIDER_TESTS=1 pytest -q tests/test_live_openai_smoke.py` also bills).
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
| Test-isolation and classifier fixes | everything, plain, reordered and with hostile environment variables | the figures in the table above. Earlier figures in this file (468 passed) predate the new failover-accounting, environment-isolation, capability and model-configuration tests. |
