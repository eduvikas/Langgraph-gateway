# Leadership dashboard

`showcase/ai-gateway-showcase.html` is a single self-contained page (no server, no network, no external files). Open it by double-clicking. It shows what one real run of the gateway did, and the numbers in it are computed in the browser from the run's own records.

## What is real and what is simulated

| Real gateway code | Simulated |
|---|---|
| Application allowlist, content security, policy, routing and ranking, atomic budget reservations, response cache, failover and circuit breaker, usage ledger, audit trail | The model provider (deterministic token counts and a scripted outage of one model) and the traffic mix |

Prices come from the repository's fixture table, so dollar figures show how the mechanics work. They are not billed spend and not a forecast of savings.

## What the page shows

- **Proof panel.** Six checks recomputed live from the raw ledger and audit rows: every request has a ledger row and an audit record; per-request costs sum to the control-tower total; blocked requests cost nothing; each app's spend equals its budget record; no app exceeded its limit; cache hits cost nothing. A failed check shows ✗.
- **Charts.** Spend per request against an all-premium baseline, where each application's requests went, and daily budgets.
- **Request table.** Every request, filterable. Click a row to see the classification, the ranked candidates, the model that ran, and the raw audit record.

## Regenerate

```powershell
python scripts/run_showcase.py      # runs the traffic through the real gateway, writes showcase/run-data.json
python scripts/build_showcase.py    # inlines the data into showcase/template.html -> ai-gateway-showcase.html
```

`--quick` runs a shorter scenario. To use real provider data instead, replace the simulated provider with real traffic exports in the same `run-data.json` shape; the page needs nothing else.

`tests/test_showcase.py` fails if the page's embedded data drifts from `run-data.json`, if the data stops reconciling, or if the page starts loading external resources.
