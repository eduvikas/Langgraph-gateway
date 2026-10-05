# AI Gateway — LangGraph + LangSmith demo

The code implementation of AI Gateway. For the full picture — the detailed
architecture diagram and the leadership-facing deck — see `../architecture/`
and `../deck/` (this file focuses on running the code).

A working (not mocked-up) implementation of the gateway concept, built as a
LangGraph state graph. Every request — from five simulated apps — flows
through the same graph: classify complexity, price the no-gateway baseline,
check the cache, check the app's budget, then either serve from cache, call
a model, or get rejected by the guardrail.

Model calls use LangChain's `FakeListChatModel`, so the whole thing runs
with **zero API keys**. LangSmith tracing is optional but is where this
gets compelling to show live — every node becomes a span in the trace tree.

## Setup (Windows, PowerShell)

```powershell
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activation script the first time, run this once
in an admin PowerShell, then retry: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Using cmd.exe instead of PowerShell? Activate with `venv\Scripts\activate.bat`.

Set your keys for the current session (PowerShell):

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:LANGCHAIN_TRACING_V2 = "true"
$env:LANGCHAIN_API_KEY = "ls__..."       # your LangSmith key, from smith.langchain.com
$env:LANGCHAIN_PROJECT = "ai-gateway-demo"
```

`$env:` variables only last for that PowerShell window. To make them
permanent across sessions, use `setx` instead (then open a **new** terminal
for it to take effect):

```powershell
setx OPENAI_API_KEY "sk-..."
setx LANGCHAIN_TRACING_V2 "true"
setx LANGCHAIN_API_KEY "ls__..."
setx LANGCHAIN_PROJECT "ai-gateway-demo"
```

macOS/Linux equivalent, if you ever run this elsewhere:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
```

## Run it offline (no tracing, no API key)

```powershell
python demo_runner.py
```

Prints a live routing table for 40 simulated requests, then a summary:
gateway spend vs. the no-gateway baseline, cache hit rate, and savings %.
Useful as a first sanity check that the venv and install worked before
wiring in real keys.

## Switch to real OpenAI models

With `OPENAI_API_KEY` set (see above), the gateway automatically routes
real calls to OpenAI instead of the mock:

```powershell
python demo_runner.py
```

`model_backends.py` maps each tier to a real model —
`gpt-4.1-nano` (small) / `gpt-4.1-mini` (mid) / `gpt-5.1` (frontier).
Nothing else changes — same graph, same routing, same guardrail. The only
functional difference: `call_model` now reads the model's actual
`usage_metadata` for token counts instead of the pre-classified estimate,
so cost figures become real rather than simulated. `max_completion_tokens`
is capped at 60 in the mock-to-real swap so a demo run doesn't rack up a
real bill — raise it once you're past the demo.

If you'd rather point this at Claude, set `ANTHROPIC_API_KEY` instead (and
`pip install langchain-anthropic`) — same behavior, different provider.
`TIER_TO_MODEL` in `model_backends.py` is where you'd edit either mapping,
including pointing "small" at a self-hosted endpoint instead of a hosted API.

## Cost-per-outcome report (the leadership number)

Cost-per-token is a finance-team argument. "Resolving a support ticket now
costs $X instead of $Y" is the one that survives being repeated outside
engineering. Each app is tagged with an outcome label (ticket resolved, PR
reviewed, contract reviewed, forecast generated, question answered), and
every non-blocked request counts as one outcome delivered.

```powershell
python roi_report.py --requests 300 --csv roi_report.csv
```

Prints a per-app table of outcomes delivered, cost per outcome, what that
outcome would have cost with no gateway, and the % reduction — plus writes
a CSV you can paste straight into a sheet or slide. `sample_roi_report.csv`
is a saved example run. Works with either the mock or a real model — set
`OPENAI_API_KEY` first if you want real numbers here too, though with 300
requests that will make 300 real API calls, so mind the cost.

## Run it with live LangSmith tracing (the actual demo)

With `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT`
set (see the setup section above — this is what "using your LangChain
account" means: LangSmith is the tracing product tied to it, and the key
comes from https://smith.langchain.com under Settings → API Keys):

```powershell
python demo_runner.py
```

Then open your project at https://smith.langchain.com. Click into any run
and you'll see the actual graph execute as a trace tree:
`classify → compute_baseline → check_cache → check_budget → call_model` (or
`serve_from_cache` / `reject` depending on the branch taken), each with its
own latency and input/output. That trace tree **is** the architecture
diagram from the slides, except it's real and clickable. If you also set
`OPENAI_API_KEY`, each `call_model` span shows the real prompt, response,
and token usage from OpenAI.

Runs are tagged by app ID, so you can filter the LangSmith project by app
(`support`, `codereview`, `contracts`, `forecast`, `wiki`) mid-demo.

## The guardrail scenario

```bash
python scenario_runaway_agent.py
```

Fires 25 large requests from one app in a tight loop, the way a stuck agent
retry-loop would. Watch the `Blocked` column flip to `True` once that app's
daily budget is exhausted — everything after that short-circuits before
touching a model, at zero cost. This is the single moment that tends to
land hardest with leadership: point at the terminal, not a slide, when it
happens.

## The policy-override scenario

```bash
python scenario_policy_override.py
```

Sends the same request twice from the same app, at the same complexity —
once plain, once flagged `data_sensitive=True`. The plain version routes to
the frontier tier as its complexity would suggest; the flagged one gets
forced onto the small, self-hosted tier regardless, and never reaches an
external API. This is step 3 of the routing pipeline on the architecture
diagram (`../architecture/ai-gateway-architecture.svg`) — policy overrides
run after complexity scoring but win over it. In `gateway_graph.py`, it's
the `data_sensitive` check inside `classify()`; `result['policy_override']`
tells you whether it fired.

In production this flag would come from an upstream PII/data-classification
check on the request, not a manual argument — wiring that in is the natural
next step here.

## The HTTP service — point a real agent at this

Everything above runs in-process, as a Python demo. `server.py` wraps the
same routing/cache/budget ideas as a real OpenAI-compatible HTTP service,
so an actual agent (LangChain's `ChatOpenAI`, the `openai` SDK, anything
that speaks the OpenAI API) can point at it by changing only `base_url`
and `api_key`. It adds what a live multi-agent integration actually needs
that the in-process demo doesn't: per-run budgets (not just per-app),
capability-aware routing (tool calls bump off the small tier), and
real request/response headers instead of return values.

```bash
uvicorn server:app --reload --port 8000
python client_demo.py   # in another terminal — proves it with the real openai SDK
```

Full request/response contract, headers, and honest limitations in
`README_SERVICE.md`.

## Integrating a real application

`integration/` has a copy-paste client helper (`gateway_client.py`), a complete LangGraph
multi-agent example, and `INTEGRATION.md` explaining what changes in the application.

## Files

- `gateway_graph.py` — the graph: state schema, nodes, conditional routing,
  the `AIGateway` class (shared cache, per-app spend, outcomes). Also where
  the policy-override logic and the `infra` field on `MODEL_PRICING` live —
  the latter documents which compute pool each tier is meant to run on,
  matching the architecture diagram's CPU/GPU/specialized/burst breakdown.
- `model_backends.py` — mocked models by default; real OpenAI models if
  `OPENAI_API_KEY` is set, or real Claude models if `ANTHROPIC_API_KEY` is
  set instead.
- `server.py` / `classifier.py` / `state_store.py` / `schemas.py` /
  `errors.py` — the OpenAI-compatible HTTP service; see `README_SERVICE.md`.
- `client_demo.py` — proves the service with the real `openai` SDK, as a
  small multi-step agent run.
- `demo_runner.py` — fires realistic mixed traffic from all 5 apps.
- `scenario_runaway_agent.py` — the budget-guardrail demo.
- `scenario_policy_override.py` — the data-sensitivity routing override demo.
- `roi_report.py` — the cost-per-outcome report, with optional CSV export.
- `sample_roi_report.csv` — a saved example of that report's output.
- `architecture.mmd` — the graph exported as Mermaid, a quick text-based
  alternative to the full diagram in `../architecture/`.

## Going from here to production

- Replace the in-memory `cache` / `spend` dicts with Redis and your real
  billing store.
- Add a `MemorySaver` or a Postgres checkpointer (`langgraph.checkpoint`)
  if you want the graph to persist and resume state across requests.
- The shadow-mode / quality-comparison idea from the earlier prototype
  slots in as one more conditional branch off `call_model`, calling a
  second, cheaper model in parallel and logging the comparison without
  serving its output.
- Wire `cost_per_outcome()` to a real outcome signal (ticket closed in
  your helpdesk tool, PR merged) instead of "request wasn't blocked" —
  that's the honest version of the same metric.
