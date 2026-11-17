# Engineering guide

`app/` is the single supported implementation. The earlier `code/` HTTP service and its duplicate root-level scripts were moved to `archive/legacy_http_gateway/` so they can be inspected but not mistaken for a second runtime.

## Request routing

1. `app/routing/classifier.py` accepts allowlisted request hints or applies transparent keyword/length heuristics.
2. `app/gateway/graph.py` filters profiles using the application's allowed-model policy.
3. It ranks eligible profiles once, saves the candidate order and uses the top candidate for governance and budget estimation.
4. `execute_node` tries the approved candidate first. Failover uses the same ranked and policy-filtered candidates; it does not re-rank independently.
5. If a configured budget exists and the selected real model has no known price, the request is blocked rather than silently treated as free.

## What this does not claim

The classifier is not an LLM judge and cannot reliably infer all task difficulty. Budget preflight uses an estimate (prompt tokens plus an assumed output allowance); admission is an atomic reservation in shared SQL storage that is settled to the provider-reported cost afterwards (see [HARDENING.md](HARDENING.md)), but it is not a guaranteed dollar ceiling if real usage exceeds the estimate. Mock-provider results demonstrate the workflow and are not evidence of production cost savings.

## Validation checklist

Current results for the items that can run without a provider key are in [VERIFICATION.md](VERIFICATION.md).

- [ ] Run `python -m compileall -q app tests`.
- [ ] Install `requirements.txt` in a clean virtual environment.
- [ ] Run `python -m pytest -q` and resolve all failures.
- [ ] Test simple, coding, reasoning and explicit routing-hint cases.
- [ ] Test that governance, budget and actual model use the same selected candidate absent failover.
- [ ] Simulate a provider outage and verify failover stays inside application policy.
- [ ] Test unknown-price behavior and budget-boundary behavior.
- [ ] Run concurrent budget tests against PostgreSQL (not just SQLite) before claiming hard budget enforcement.
- [ ] Compare quality, latency and provider-reported cost against a baseline before claiming savings.
