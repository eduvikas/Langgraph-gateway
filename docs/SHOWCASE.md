# Leadership dashboard

`showcase/ai-gateway-showcase.html` is a single self-contained page (no server, no network, no external files). Open it by double-clicking. It shows what one real run of the gateway did, and the numbers in it are computed in the browser from the run's own records.

## What is real and what is simulated

| Real gateway code | Simulated |
|---|---|
| Application allowlist, content security, policy, routing and ranking, atomic budget reservations, response cache, failover and circuit breaker, usage ledger, audit trail | The model provider (deterministic token counts and a scripted outage of one model) and the traffic mix |

Prices come from the repository's fixture table, so dollar figures show how the mechanics work. They are not billed spend and not a forecast of savings.

## What the page shows

- **Proof panel.** Six checks recomputed live from the raw ledger and audit rows: every request has a ledger row and an audit record; per-request costs sum to the control-tower total; blocked requests cost nothing; each app's spend equals its budget record; no app exceeded its limit; cache hits cost nothing. A failed check shows ✗.
- **Source badge.** Reads “Simulated model provider” or “Real OpenAI provider”, set by the run data, so the page can never pass one off as the other.
- **Four layers keep spend bounded.** (1) OpenAI’s hard project limit, which only the OpenAI dashboard can show; (2) the preflight result and the worst case computed before the run; (3) per-application budgets and how many requests they stopped; (4) approved models per app and an output cap that the reservation fully covers.
- **Reconcile with OpenAI’s usage page.** Type in the token totals from your project’s usage page; the page compares them with the gateway ledger and flags anything more than 2% apart. Nothing you type is stored.
- **Charts.** Spend per request against an all-premium baseline, where each application's requests went, and daily budgets.
- **Request table.** Every request, filterable. Click a row to see the classification, the ranked candidates, the model that ran, and the raw audit record.

## Regenerate

```powershell
python scripts/run_showcase.py      # runs the traffic through the real gateway, writes showcase/run-data.json
python scripts/build_showcase.py    # inlines the data into showcase/template.html -> ai-gateway-showcase.html
```

`--quick` runs a shorter scenario.

## Present real OpenAI data

After the steps in [REAL_PROVIDER.md](REAL_PROVIDER.md) work (preflight passes, one real call succeeds, usage reconciles):

```powershell
python scripts/run_showcase.py --live --confirm-spend --quick --max-usd 0.50
python scripts/build_showcase.py
```

Live mode uses your `.env` (key, model IDs, prices), runs the preflight first, computes the worst-case spend and refuses if it exceeds `--max-usd`, stops at the first provider failure without writing anything, and skips the outage scene because a real provider cannot be made to fail on cue. Its intern-sandbox budget is set so the gateway stops the third request at real prices. Then open the page, enter the totals from OpenAI’s usage page in the reconcile panel, and present.

To use something other than the default model IDs, set `SHOWCASE_MODELS` (three comma-separated IDs for the premium, mid and low-cost tiers). Any run data in the same `run-data.json` shape renders in the page.

`tests/test_showcase.py` also exercises the live-mode gates (no `--confirm-spend`, failing preflight, worst case over the cap) and an end-to-end live run with a simulated OpenAI reply. It fails if the page's embedded data drifts from `run-data.json`, if the data stops reconciling, or if the page starts loading external resources.
