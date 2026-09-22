# AI gateway — LangGraph + LangSmith demo

A working (not mocked-up) implementation of the gateway concept, built as a
LangGraph state graph. Every request — from five simulated apps — flows
through the same graph: classify complexity, price the no-gateway baseline,
check the cache, check the app's budget, then either serve from cache, call
a model, or get rejected by the guardrail.

Model calls use LangChain's `FakeListChatModel`, so the whole thing runs
with **zero API keys**. LangSmith tracing is optional but is where this
gets compelling to show live — every node becomes a span in the trace tree.

## Setup

```bash
pip install -r requirements.txt
```

## Run it offline (no tracing)

```bash
python demo_runner.py
```

Prints a live routing table for 40 simulated requests, then a summary:
gateway spend vs. the no-gateway baseline, cache hit rate, and savings %.

## Run it with live LangSmith tracing (the actual demo)

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=<your LangSmith API key>   # free tier is fine
export LANGCHAIN_PROJECT=ai-gateway-demo

python demo_runner.py
```

Then open your project at https://smith.langchain.com. Click into any run
and you'll see the actual graph execute as a trace tree:
`classify → compute_baseline → check_cache → check_budget → call_model` (or
`serve_from_cache` / `reject` depending on the branch taken), each with its
own latency and input/output. That trace tree **is** the architecture
diagram from the slides, except it's real and clickable.

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

## Files

- `gateway_graph.py` — the graph: state schema, nodes, conditional routing,
  the `AIGateway` class (holds the shared cache and per-app spend).
- `demo_runner.py` — fires realistic mixed traffic from all 5 apps.
- `scenario_runaway_agent.py` — the budget-guardrail demo.
- `architecture.mmd` — the graph exported as Mermaid, if you want a static
  diagram alongside the live trace (paste into mermaid.live or a docs page).

## Going from here to production

- Swap `make_mock_model()` for real `ChatAnthropic` / `ChatOpenAI` /
  self-hosted vLLM clients — the graph, routing, and guardrail logic don't
  change, only what's inside `call_model`.
- Replace the in-memory `cache` / `spend` dicts with Redis and your real
  billing store.
- Add a `MemorySaver` or a Postgres checkpointer (`langgraph.checkpoint`)
  if you want the graph to persist and resume state across requests.
- The shadow-mode / quality-comparison idea from the earlier prototype
  slots in as one more conditional branch off `call_model`, calling a
  second, cheaper model in parallel and logging the comparison without
  serving its output.
