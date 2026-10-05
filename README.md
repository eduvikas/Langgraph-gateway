# AI Gateway

An enterprise AI gateway that routes every request to the cheapest capable
model tier, caches repeat questions, enforces per-app budgets, and reports
cost per business outcome instead of just cost per token.

## What's in here

- **`code/`** — the working implementation. A LangGraph state graph you can
  actually run: `pip install -r code/requirements.txt`, then
  `python code/demo_runner.py`. Runs with zero API keys out of the box;
  see `code/README.md` for wiring in real OpenAI or Claude models, live
  LangSmith tracing, and the three demo scenarios (runaway-agent guardrail,
  policy override, cost-per-outcome report). Also includes `server.py` — a
  real OpenAI-compatible HTTP service a live agent can point at (see
  `code/README_SERVICE.md`), proven end to end with `client_demo.py` using
  the actual `openai` SDK.

- **`architecture/`** — the detailed reference architecture.
  `ai-gateway-architecture.svg` (vector, editable in Illustrator/Inkscape/
  any text editor) and a rendered `.png` of the same diagram. Covers the
  full routing/decision pipeline — feature extraction, complexity scoring,
  policy override, cache lookup, budget guardrail, tier thresholds — and
  the small tier's breakdown into CPU cluster, GPU cluster, specialized
  accelerator cluster, and burst/spot GPU cluster, each with the reasoning
  behind it.
  `ai-gateway-integration-overview.png` is the one-page high-level view
  with the "how it fits into the bank's existing ecosystem" section added.

- **`deck/`** — `ai-gateway-overview.pptx`, 4 slides, fully editable in
  PowerPoint: the problem, challenges vs. benefits, technology stack, and
  the roadmap. Built to match the diagram and dashboard visually (same
  navy/teal/amber/coral palette throughout).

- **`dashboard/`** — `ai-gateway-dashboard.html`, the interactive browser
  demo: live simulated traffic, a policy-override demo ("Inject sensitive
  request" forces the small tier regardless of complexity — the live
  version of `code/scenario_policy_override.py`), shadow-mode routing
  evaluation, a cost-per-outcome panel, a small-tier infrastructure
  breakdown (CPU / GPU / specialized / burst), and CSV upload to replay
  real usage data. Open the `.html` file directly in a browser, no install
  needed. `sample-usage.csv` is a ready-made file to try the upload with,
  including a `sensitive` column example.

- **`earlier-poc/`** — a separate, earlier proof of concept (standard library only):
  five mock apps, four scenarios replayed on identical traffic, SQLite metering. It
  models cost and savings; `code/` is the live service. See its own README.

- **`GUIDE.md`** — start here: step-by-step walkthrough, how complexity and token
  counts are calculated, and likely Q&A.

## Suggested order for a leadership walkthrough

1. **Deck, slides 1–2** — the problem and the challenges/benefits framing.
2. **Architecture diagram** — how a request actually gets routed, and why
   the self-hosted tiers are split the way they are.
3. **Dashboard** — click "Start traffic," then "Inject runaway agent" with
   guardrails on vs. off. Then "Inject sensitive request" to show the same
   contract-summarizer request routing two different ways depending on a
   data-sensitivity flag. This is the moment that tends to land.
4. **Code, live** — `python scenario_policy_override.py` and
   `python scenario_runaway_agent.py` in a terminal, or the same traffic
   traced live in LangSmith if you've set that up beforehand.
5. **Deck, slides 3–4** — technology stack and roadmap, to close.

## Consistency note

The diagram, deck, and dashboard intentionally share one visual language
(teal = small/self-hosted tier, amber = mid tier, coral = frontier tier) so
the audience doesn't have to re-learn a color code between artifacts. If
you rebrand or re-theme any one of them, update the others to match.
