# AI Gateway service — an OpenAI-compatible HTTP layer

This is the answer to "how do I actually point a real agent at AI Gateway":
a FastAPI service exposing an OpenAI-compatible `/v1/chat/completions`,
built on top of the same routing, caching, and budget ideas as the rest of
this project — but as a real, running HTTP service instead of an in-process
Python demo.

Every claim below has been run against a live server and checked; it isn't
aspirational.

## Run it

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Runs fully mocked with zero API keys, same as the rest of the project. Set
`OPENAI_API_KEY` (and optionally `pip install langchain-anthropic` +
`ANTHROPIC_API_KEY`) to route real calls — see `model_backends.py`.

Then point a real client at it:

```bash
python client_demo.py
```

This uses the actual `openai` Python SDK (the same one LangChain's
`ChatOpenAI` wraps) against `base_url="http://localhost:8000/v1"`. Nothing
else about how an agent calls a model changes. It walks through:
1. An ordinary step — routes on complexity alone.
2. A step with a tool attached — capability-aware routing bumps it off
   the small tier, since that tier isn't routed tool calls reliably.
3. A step flagged data-sensitive — policy override forces the small,
   self-hosted tier regardless of complexity.
4. A tight-budget loop — the run-level guardrail blocks it with a 429
   after a few steps, instead of an open-ended bill.

## How an agent integrates

Change the client's base URL and key, tag calls with headers, done:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://ai-gateway.internal/v1",
    api_key=AGENT_VIRTUAL_KEY,
)

resp = client.chat.completions.create(
    model="ai-gateway/auto",   # or "ai-gateway/small" / "mid" / "frontier" to pin
    messages=[{"role": "user", "content": "..."}],
    extra_headers={
        "X-App-Id": "claims",
        "X-Agent": "planner",
        "X-Run-Id": run_id,      # same id across every step of one agent run
        "X-Step": str(step_num),
    },
)
```

LangChain's `ChatOpenAI` takes the same two things (`base_url`, `api_key`)
plus `default_headers` for the rest — see the snippet in the project's
main README / the conversation that led here.

## Request contract

Standard OpenAI chat completion fields (`model`, `messages`, `tools`,
`tool_choice`, `temperature`, `max_tokens`, `stream`) plus AI Gateway's
routing context, which can travel as headers **or** inside the JSON body's
`metadata` object (useful for clients that can't easily set custom
headers):

| Header             | Body (`metadata.`) | Meaning                                              |
|---------------------|---------------------|-------------------------------------------------------|
| `X-App-Id`          | `app_id`            | Which app/team is calling. Drives the daily budget.   |
| `X-Agent`           | `agent`              | Free-text label, shows up in trace tags.              |
| `X-Run-Id`          | `run_id`             | One id per agent run — carries the run-level budget.  |
| `X-Step`            | `step`               | Step number in the run; nudges the complexity score.  |
| `X-Sensitivity`     | `data_sensitive`     | `true` forces the small, self-hosted tier.            |
| `X-Min-Tier`        | `min_tier`           | Floor: `small`, `mid`, or `frontier`.                 |
| `X-Max-Tier`        | `max_tier`           | Ceiling: same values.                                 |
| `X-Run-Max-Budget`  | `run_max_budget`     | USD cap for this run_id. Fixed at the run's first call. |
| `X-Run-Max-Steps`   | `run_max_steps`      | Step cap for this run_id. Also fixed at first call.   |
| `X-Parent-Trace-Id` | —                    | Best-effort LangSmith nesting — see Limitations.      |

The `model` field itself is also a routing lever: `"ai-gateway/auto"` runs
the classifier; `"ai-gateway/small"` / `"mid"` / `"frontier"` pins a tier
outright (still subject to the policy override — sensitive data doesn't
escape to a pinned frontier tier; see Conflicts below).

## Response contract

Standard OpenAI response shape, plus these headers on every response:

- `X-AI-Gateway-Tier` — which tier actually served this
- `X-AI-Gateway-Cache` — `hit` or `miss`
- `X-AI-Gateway-Cost` — USD, this call
- `X-AI-Gateway-Complexity-Score`, `X-AI-Gateway-Policy-Override`,
  `X-AI-Gateway-Capability-Override` — why it was routed where it was
- `X-AI-Gateway-Run-Id`, `X-AI-Gateway-Run-Spend` — running total for this run
- `X-AI-Gateway-Reasons` — human-readable trail of every routing decision

Streaming (`stream: true`) works the same way over SSE; a final chunk
carries `usage` before `[DONE]`, matching OpenAI's `include_usage`
convention. Cost/run-spend headers aren't set on streaming responses,
since the real cost isn't known until the stream finishes — check
`/v1/outcomes` afterward instead.

## Conflicts are rejected, not silently resolved

If a caller sets `X-Sensitivity: true` **and** `X-Min-Tier: frontier` on
the same request, that's a genuine conflict — compliance says small tier
only, the caller explicitly demanded at least frontier. The service
returns `403 policy_conflict` rather than picking a winner quietly. Budget
and step-limit breaches return `429 budget_exceeded`. Both carry `x-should-retry: false`, because the OpenAI SDK retries 429s by default and a permanent budget block would otherwise freeze the calling agent for minutes.
Both follow OpenAI's error envelope shape (`{"error": {"message", "type",
"code"}}`, nested under `detail` since that's how FastAPI wraps it).

## Other endpoints

- `GET /health` — backend mode (mock/real) and provider
- `GET /v1/models` — lists the four `ai-gateway/*` model ids
- `GET /v1/admin/policy` — current thresholds, pricing, infra mapping (read-only for now)
- `PATCH /v1/admin/apps/{app_id}?daily_budget=...` — override an app's daily budget
- `GET /v1/outcomes` — per-app spend, baseline, cost-per-outcome, blocked count

## Caching, budget, and logging are aspects, not inline code

`aspects.py` pulls caching, budget enforcement, and observability out of
the endpoint and into three decorators (`with_cache`, `with_budget`,
`with_observability`), stacked around `_invoke()` — the one function in
`server.py` that actually calls a model:

```python
@with_observability
@with_cache
@with_budget
async def _invoke(ctx: CallContext, model, lc_messages, config) -> CallContext:
    ...  # just "call the model, work out what it cost" — nothing else
```

This is the standard way to get AOP's effect in Python: there's no
dedicated AOP framework in the language, so a decorator stands in for an
aspect, and "wherever the decorator is applied" stands in for a pointcut.
`_invoke` itself no longer knows or cares that caching or budgets exist.

One honest wrinkle: the streaming path can't use these decorators
directly — a decorator that wraps a function returning one `CallContext`
doesn't compose with a generator yielding many SSE chunks over time. So
`stream_model` in `server.py` calls the same underlying plain functions
(`reserve_budget`, `finalize_cost`, `check_cache`) directly, at the right
points in its generator. Same logic, enforced once, in `aspects.py` — just
two different calling conventions depending on whether the thing being
wrapped returns once or streams.

## What's simplified here — be upfront about these

- **State is in-process and single-worker.** Cache, app spend, and run
  budgets are plain dicts behind one lock. Run more than one worker or
  instance and they stop agreeing with each other. Swap for Redis
  (`INCRBYFLOAT` for spend, a Lua script for atomic check-then-spend,
  `SET ... EX` for the cache) before that matters — `state_store.py` marks
  exactly where.
- **The budget check has a small race.** Cost is reserved as an *estimate*
  before the model call, then corrected to the real cost after. Two
  concurrent requests on the same run can both pass the check against a
  stale reserved total. Fine for a demo; not fine at real concurrency —
  needs the atomic version above.
- **Tool calls only round-trip through the real OpenAI backend**
  (`model.bind_tools(...)`). The mock model and the Anthropic backend
  don't execute or forward tool schemas — `has_tools` is only used for
  routing (the capability override), not tool execution, on those paths.
- **`X-Parent-Trace-Id` is relayed as metadata, not a real parent span.**
  Full distributed tracing (one nested tree spanning the agent's own
  LangSmith run and AI Gateway's spans) needs the calling app's LangSmith
  SDK to cooperate, not just a header.
- **Streaming uses estimated output tokens even with a real model** (`len(text) / 4`);
  the non-streaming path reads the provider's real usage. Pricing is one blended rate
  per tier, not separate input and output prices.
- **Token counts are `chars / 4`.** Replace with a real tokenizer
  (`tiktoken`, or the provider's own counting endpoint) before trusting
  the numbers for billing.
- **Baseline cost (for `/v1/outcomes`) is priced off the estimated input
  tokens only**; actual cost includes completion tokens too. They're not
  perfectly comparable yet — close enough to see the shape of the savings,
  not close enough to reconcile penny for penny.
- **The routing thresholds are constants, not runtime-editable.** Good
  enough for a demo; a real "governed, reviewable configuration" (as
  pitched in the integration conversation) means these live in a database
  with an audit trail, not in `classifier.py`.
