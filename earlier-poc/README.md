# Enterprise AI gateway: hands-on proof of concept

A working control plane for LLM spend, fed by five mocked applications. The control logic
is real (metering, auth keys, PII redaction, caching, routing, budgets, circuit breaker,
failover). Only the model backends and the numbers are mocked. Python 3.9+, no dependencies.

## Run it (2 minutes)

    python simulate.py        # 14.5k calls, same day run four ways -> results.json, usage.db
    python report.py          # -> dashboard.html (open in a browser)
    python -m unittest -v     # 6 sanity tests on the control logic
    python server.py          # live gateway on :8080 (see below)

## The five dummy applications

| App | Team | Profile | Lever that matters most |
|---|---|---|---|
| support-copilot | Customer Care | high volume, mostly easy, repeated FAQs | routing + caching |
| code-review-bot | Engineering | big inputs, half the tasks hard | (little: needs a frontier model) |
| doc-summarizer | Legal Ops | very long inputs, medium difficulty | routing to mid-tier |
| hr-faq-bot | People | tiny prompts, lots of PII, data must stay in EU/on-prem | routing + policy |
| research-agent | Strategy | chained agent calls, 2% of runs loop forever | circuit breaker |

## The four scenarios (identical traffic)

1. Direct to frontier: how teams call models today.
2. + Smart routing: cheapest model that is allowed, has capacity, and meets the app's quality floor.
3. + Caching: response cache (exact and semantic, per app) and provider prompt caching.
4. + Budgets and circuit breaker: PII redaction, residency policy, budgets, loop breaker, failover.

## Where things live

    gateway/config.py      model catalogue, prices, fleet, apps, budgets, policies  (edit these)
    gateway/router.py      difficulty classifier + "cheapest model that qualifies" selection
    gateway/cache.py       response cache (swap the similarity for embeddings in production)
    gateway/guardrails.py  PII and secret redaction, circuit breaker
    gateway/core.py        the request pipeline: guardrails > breaker > budget > cache > route > call > meter
    gateway/meter.py       SQLite metering with ready-made views
    gateway/workload.py    synthetic traffic for the five apps
    simulate.py            runs the four scenarios      report.py  builds the dashboard
    server.py              the same gateway as a live HTTP endpoint

## Live endpoint

    python server.py
    curl -s localhost:8080/v1/chat -H 'Authorization: Bearer sk-hr-demo' \
         -d '{"prompt":"How many vacation days do I get"}'
    curl -s localhost:8080/v1/chat -H 'Authorization: Bearer sk-hr-demo' \
         -d '{"prompt":"Hi, how many vacation days do I get please"}'      # semantic cache hit, cost 0
    curl -s localhost:8080/v1/chat -H 'Authorization: Bearer sk-hr-demo' \
         -d '{"prompt":"My email is jane@corp.example.com, when is payroll"}'  # redacted before routing
    curl -s localhost:8080/metrics

Keys: sk-support-demo, sk-code-demo, sk-docs-demo, sk-hr-demo, sk-research-demo.
For an agent loop, add "run_id":"job-1" to the body and call it 30 times: the breaker returns 429.

## Ask the data anything (SQLite)

    sqlite3 usage.db "SELECT * FROM v_cost_by_app WHERE scenario LIKE '+ Budgets%'"
    sqlite3 usage.db "SELECT model, COUNT(*), ROUND(SUM(cost),2) FROM usage GROUP BY model"

## Experiments to run live in the room

- Set `daily_budget` for hr-faq-bot to 0.05 in config.py and re-run: the hard limit blocks calls (429).
- Remove "onprem" from an app's `allowed_regions` and watch traffic move to another region.
- Raise `min_quality` to 0.95 for an app and watch spend climb: quality has a price.
- `python simulate.py --scale 5` for 5x traffic: the GPU fleet saturates and spillover grows.
- Set `RUNAWAY_RATE = 0` and see how much of the baseline bill was loops.

## Honest caveats (say these before anyone asks)

- All prices, volumes, latencies and quality scores are illustrative. Quality is a modelled
  acceptable-answer rate, not a measured score. Replace with your price sheet and real evals.
- The difficulty classifier is a keyword heuristic (about 89% accurate here). Production needs a
  trained classifier and an evaluation set per use case, run in shadow mode before going live.
- "Semantic" cache uses token overlap so the PoC has no dependencies. Use embeddings plus a
  vector store in production, keep the cache scoped per app, and never cache stateful agent calls.
- The GPU fleet cost is fixed and identical in every scenario (you already own it). The gateway's
  effect is higher utilisation. At low utilisation the effective $ per token is high, which is
  itself a finding.

## From PoC to pilot

Keep gateway/core.py's pipeline and swap the mocks: put LiteLLM, Kong AI Gateway or Envoy AI
Gateway in front for the OpenAI-compatible proxy, call real providers (Bedrock, Azure OpenAI,
etc.) and vLLM on your GPU clusters as backends, send metering to OpenTelemetry, Grafana and S3/Athena
instead of SQLite, and load apps, budgets and policies from a config repo (policy as code).
