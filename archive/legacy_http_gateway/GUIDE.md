# ai-gateway: step-by-step guide

## 1. What is in this zip

| Folder | What it is | How real it is |
|---|---|---|
| `code/` | LangGraph gateway, OpenAI-compatible FastAPI service, aspect decorators, demo scripts | Service is real HTTP and tested; routing signal is simple (see section 4) |
| `architecture/` | Detailed diagram (SVG/PNG) and the one-page integration overview | Reference design |
| `deck/` | 4-slide editable PowerPoint | Pitch material |
| `dashboard/` | Browser demo, no install | Simulated traffic |
| `earlier-poc/` | Separate, earlier proof of concept (stdlib only, SQLite metering, 5 mock apps, 4 scenarios) | Control logic real, models and numbers mocked |

The two codebases are independent. `code/` is the HTTP service a real agent can point at.
`earlier-poc/` is the cost model: it replays 14.5k calls four ways to show where the savings come from.

## 2. One-paragraph idea

Put one gateway between every application and every model. It classifies each request, sends it
to the cheapest tier that can handle it, serves repeats from cache, enforces budgets, forces
sensitive data onto self-hosted compute, and reports cost per business outcome.

## 3. A request's journey through the service (code/server.py)

1. **Read context.** App, agent, run id, step, sensitivity, min/max tier come from `X-` headers
   (or the body's `metadata`). `model` is `ai-gateway/auto` (router decides) or a pinned tier.
2. **Decide the tier** (`classifier.decide_tier`): score the request, then apply overrides in
   this order: capability (tools bump small to mid), policy (sensitive forces small), caller's
   min/max tier. Sensitive plus min_tier above small is a conflict and returns 403.
3. **Build a call context.** Cacheable only if no tools and temperature <= 0.05. Cache key is a
   hash of app + messages + tools. Input tokens are estimated, a pre-call cost estimate is made,
   and a "no-gateway" baseline (frontier price) is recorded for savings reporting.
4. **Aspects run** (`aspects.py`, outermost first): observability, cache, budget, then the call.
   A cache hit stops everything below it: free, and it never touches the budget.
5. **Budget check.** The estimate is reserved against the app's daily budget and the run's
   budget and step cap. Over either: 429 with an OpenAI-shaped error.
6. **Model call** through LangChain (mock by default; OpenAI or Claude if a key is set).
7. **True-up.** Real usage replaces the estimate, spend and counters update, cacheable answers
   are stored.
8. **Response** is the standard OpenAI body plus `X-AI-Gateway-*` headers (tier, cache, cost,
   overrides, run spend, reasons). `/v1/outcomes` aggregates cost per outcome.
9. **Streaming** follows the same steps but calls the shared functions directly, because a
   generator cannot be wrapped like a normal function.

## 4. How the complexity of a request is determined

There are three different implementations in this zip. Be clear which one you are talking about.

**A. Demo scripts and dashboard (code/gateway_graph.py, dashboard/).** Complexity is not
computed. It is sampled at random from each app's configured mix (for example 75% simple),
then a token count is drawn from a range. It exists to drive a simulation.

**B. The HTTP service (code/classifier.py).** Complexity is a size score:

    token_estimate = total characters across all messages / 4
    score = min(1, 0.85 * min(tokens / 6000, 1) + 0.15 * min(step / 10, 1))
    score < 0.30 -> small     0.30 to 0.70 -> mid     > 0.70 -> frontier

With step 0, mid starts at about 2,100 tokens and frontier at about 4,900. At step 10 (late in
an agent loop, more accumulated context) those drop to about 1,050 and 3,900. Worked results
from the real code: a 1-line FAQ scores 0.001 (small); a 3,000-token summary scores 0.425 (mid);
a 6,000-token contract scores 0.85 (frontier).

**Limitation, say it first:** this measures size, not difficulty. "Prove that sqrt(2) is
irrational" scores 0.001 and routes to the small tier. A long but trivial paste routes up. Tools
and sensitivity are handled as separate overrides, not folded into the score.

**C. The earlier POC (earlier-poc/gateway/router.py).** A keyword heuristic: a code fence adds
1; hard hints ("analy", "refactor", "root cause", "forecast", "debug"...) add 2; medium hints
("summar", "explain", "compare"...) add 1; over 8,000 input tokens with no hints adds 1. Score
2+ is hard, 1 is medium, 0 is easy. Its README reports about 89% accuracy, measured on the POC's
own synthetic traffic, so treat that as optimistic. Model choice then picks the cheapest model
that is allowed (data residency), has capacity (own GPUs) and meets the app's quality floor for
the predicted difficulty.

**What production needs:** a trained classifier or small judge model, labelled examples per use
case, and shadow mode (run the cheaper route in parallel, compare quality, only then switch).
A common extra safety net is cascading: try the cheap model, verify, escalate on failure.

## 5. How tokens and cost are calculated

**Input tokens.** The provider returns the exact count. Before the call the service estimates
characters / 4. The POC live server uses words x 1.3 plus the system prompt. For exact
pre-call counts use the provider's tokenizer (tiktoken for OpenAI, Anthropic's count-tokens
endpoint). Different providers tokenize the same text differently.

**Output tokens.** They cannot be known before the call, only capped (`max_tokens`) or
estimated from history. After the call the truth is in the response:
OpenAI `usage.completion_tokens`, Anthropic `usage.output_tokens`; LangChain normalizes both
to `usage_metadata["output_tokens"]`, which is what the service reads in real mode. For
reasoning or thinking models, hidden reasoning tokens are billed as output tokens.

Where this code approximates output tokens:
- Mock mode and any response without usage data: `len(content) / 4`.
- **Streaming path: always `len(text) / 4`, even with a real model.** Real streamed usage
  arrives in a final chunk only if you ask for it. Reading it is the fix.
- Earlier POC simulation: sampled from a per-app range, scaled 0.7 / 1.0 / 1.3 by difficulty.

**Cost.** Real pricing is per direction:

    cost = input_tokens x input_price + output_tokens x output_price - cached-input discount

The earlier POC does this (output priced 3 to 5 times input, plus provider prompt-cache
discounts). **The `code/` service uses one blended price per tier**, a simplification that
understates output-heavy calls. The pre-call budget reservation is also priced on input tokens
only, then corrected after the call.

## 6. Questions an architect will probably ask

- **Is the router smart?** No. It is a size heuristic. The value shown is the control plane,
  with a path to a learned router behind shadow mode.
- **Can savings be trusted?** Illustrative. Prices, volumes and quality scores are placeholders.
  Replace with your price sheet and measure on your own traffic.
- **Concurrency?** State is in-process with a small check-then-spend race. Production needs Redis
  with atomic operations.
- **Why does a sensitive request never reach an external API?** Policy override runs last and
  wins over complexity, capability and pins, and conflicts are rejected with a 403.

## 7. How to run each piece

- Service: `cd code && pip install -r requirements.txt && uvicorn server:app --port 8000`, then
  `python client_demo.py` in a second terminal.
- Demo scripts: `python demo_runner.py`, `scenario_runaway_agent.py`, `scenario_policy_override.py`,
  `roi_report.py`.
- Dashboard: open `dashboard/ai-gateway-dashboard.html` in a browser.
- Earlier POC: `cd earlier-poc && python simulate.py && python report.py && python -m unittest`.
