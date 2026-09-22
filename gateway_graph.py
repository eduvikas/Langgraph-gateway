"""
AI Gateway built on LangGraph.

Every request flows through one graph: classify -> compute baseline cost ->
check cache -> check budget -> either serve from cache, call a model, or get
rejected by the budget guardrail. Run it with LangSmith tracing enabled
(see README.md) and every node shows up as a span in the trace tree.

Model calls use LangChain's FakeListChatModel so the demo runs with zero
API keys. Swap `make_mock_model` for a real ChatAnthropic / ChatOpenAI to
point this at live models — the graph and routing logic don't change.
"""
import hashlib
import random
import uuid
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from model_backends import make_model, REAL_MODELS_ENABLED

# ---------------------------------------------------------------------------
# Model backends — mocked by default, real Claude calls if ANTHROPIC_API_KEY
# is set (see model_backends.py). Pricing below is illustrative; replace
# with your negotiated or list pricing per tier.
# ---------------------------------------------------------------------------
MODEL_PRICING = {
    "small":    {"price_per_m_tokens": 0.15,  "label": "Self-hosted small (Llama-class)"},
    "mid":      {"price_per_m_tokens": 3.00,  "label": "Mid-tier API (Haiku-class)"},
    "frontier": {"price_per_m_tokens": 15.00, "label": "Frontier API (Opus-class)"},
}

MODELS = {tier: make_model(tier) for tier in MODEL_PRICING}

# ---------------------------------------------------------------------------
# App registry — 5 mock applications sharing the gateway. outcome_label is
# what leadership actually cares about: not "tokens", but "tickets
# resolved" or "PRs reviewed" — the unit cost-per-outcome is reported in.
# ---------------------------------------------------------------------------
APPS = {
    "support":     {"name": "Support copilot",        "daily_budget": 40.0, "outcome_label": "ticket resolved",     "mix": {"simple": 0.75, "medium": 0.22, "complex": 0.03}},
    "codereview":  {"name": "Code review assistant",  "daily_budget": 35.0, "outcome_label": "PR reviewed",         "mix": {"simple": 0.30, "medium": 0.55, "complex": 0.15}},
    "contracts":   {"name": "Contract summarizer",    "daily_budget": 25.0, "outcome_label": "contract reviewed",   "mix": {"simple": 0.10, "medium": 0.35, "complex": 0.55}},
    "forecast":    {"name": "Sales forecast agent",   "daily_budget": 20.0, "outcome_label": "forecast generated",  "mix": {"simple": 0.15, "medium": 0.35, "complex": 0.50}},
    "wiki":        {"name": "Internal wiki Q&A",      "daily_budget": 15.0, "outcome_label": "question answered",   "mix": {"simple": 0.80, "medium": 0.18, "complex": 0.02}},
}

TOKEN_RANGE = {"simple": (300, 800), "medium": (800, 2500), "complex": (2500, 8000)}
TIER_BY_COMPLEXITY = {"simple": "small", "medium": "mid", "complex": "frontier"}


class GatewayState(TypedDict, total=False):
    request_id: str
    app_id: str
    prompt: str
    complexity: str
    tokens: int
    tier: str
    cache_hit: bool
    blocked: bool
    cost: float
    baseline_cost: float
    response: str
    force_tokens: int


class AIGateway:
    """Wraps the compiled LangGraph and the gateway's shared state (cache, spend)."""

    def __init__(self):
        self.cache: dict[str, str] = {}
        self.spend: dict[str, float] = {app_id: 0.0 for app_id in APPS}
        self.baseline_by_app: dict[str, float] = {app_id: 0.0 for app_id in APPS}
        self.outcomes: dict[str, int] = {app_id: 0 for app_id in APPS}
        self.total_baseline = 0.0
        self.total_requests = 0
        self.cache_hits = 0
        self.blocked_count = 0
        self.graph = self._build_graph()

    # ---------------- nodes ----------------
    def classify(self, state: GatewayState) -> GatewayState:
        forced = state.get("complexity")
        if forced in TOKEN_RANGE:
            complexity = forced
        else:
            app = APPS[state["app_id"]]
            r, mix = random.random(), app["mix"]
            if r < mix["simple"]:
                complexity = "simple"
            elif r < mix["simple"] + mix["medium"]:
                complexity = "medium"
            else:
                complexity = "complex"
        if state.get("force_tokens"):
            tokens = state["force_tokens"]
        else:
            lo, hi = TOKEN_RANGE[complexity]
            tokens = random.randint(lo, hi)
        return {**state, "complexity": complexity, "tokens": tokens, "tier": TIER_BY_COMPLEXITY[complexity]}

    def compute_baseline(self, state: GatewayState) -> GatewayState:
        baseline = (state["tokens"] / 1_000_000) * MODEL_PRICING["frontier"]["price_per_m_tokens"]
        self.total_baseline += baseline
        self.baseline_by_app[state["app_id"]] += baseline
        return {**state, "baseline_cost": baseline}

    def check_cache(self, state: GatewayState) -> GatewayState:
        key = self._cache_key(state["prompt"])
        hit = key in self.cache
        if hit:
            self.cache_hits += 1
        return {**state, "cache_hit": hit}

    def check_budget(self, state: GatewayState) -> GatewayState:
        projected = (state["tokens"] / 1_000_000) * MODEL_PRICING[state["tier"]]["price_per_m_tokens"]
        over_budget = self.spend[state["app_id"]] + projected > APPS[state["app_id"]]["daily_budget"]
        if over_budget:
            self.blocked_count += 1
        return {**state, "blocked": over_budget}

    def call_model(self, state: GatewayState) -> GatewayState:
        model = MODELS[state["tier"]]
        result = model.invoke([HumanMessage(content=state["prompt"])])
        # Real models report actual usage; the mock doesn't, so fall back
        # to the pre-classified estimate in that case.
        usage = getattr(result, "usage_metadata", None)
        tokens = usage["total_tokens"] if usage and usage.get("total_tokens") else state["tokens"]
        cost = (tokens / 1_000_000) * MODEL_PRICING[state["tier"]]["price_per_m_tokens"]
        self.spend[state["app_id"]] += cost
        self.cache[self._cache_key(state["prompt"])] = result.content
        return {**state, "tokens": tokens, "cost": cost, "response": result.content}

    def serve_from_cache(self, state: GatewayState) -> GatewayState:
        return {**state, "cost": 0.0, "blocked": False, "response": self.cache[self._cache_key(state["prompt"])]}

    def reject(self, state: GatewayState) -> GatewayState:
        return {**state, "cost": 0.0, "response": "[blocked: daily budget exceeded for this app]"}

    # ---------------- conditional routing ----------------
    def route_after_cache(self, state: GatewayState) -> str:
        return "serve_from_cache" if state["cache_hit"] else "check_budget"

    def route_after_budget(self, state: GatewayState) -> str:
        return "reject" if state["blocked"] else "call_model"

    # ---------------- graph construction ----------------
    def _build_graph(self):
        g = StateGraph(GatewayState)
        g.add_node("classify", self.classify)
        g.add_node("compute_baseline", self.compute_baseline)
        g.add_node("check_cache", self.check_cache)
        g.add_node("check_budget", self.check_budget)
        g.add_node("call_model", self.call_model)
        g.add_node("serve_from_cache", self.serve_from_cache)
        g.add_node("reject", self.reject)

        g.set_entry_point("classify")
        g.add_edge("classify", "compute_baseline")
        g.add_edge("compute_baseline", "check_cache")
        g.add_conditional_edges("check_cache", self.route_after_cache, {
            "serve_from_cache": "serve_from_cache",
            "check_budget": "check_budget",
        })
        g.add_conditional_edges("check_budget", self.route_after_budget, {
            "call_model": "call_model",
            "reject": "reject",
        })
        g.add_edge("call_model", END)
        g.add_edge("serve_from_cache", END)
        g.add_edge("reject", END)
        return g.compile()

    # ---------------- public API ----------------
    def process(self, app_id: str, prompt: str, force_complexity: str | None = None, force_tokens: int | None = None) -> GatewayState:
        self.total_requests += 1
        initial: GatewayState = {"request_id": str(uuid.uuid4())[:8], "app_id": app_id, "prompt": prompt}
        if force_complexity:
            initial["complexity"] = force_complexity
        if force_tokens:
            initial["force_tokens"] = force_tokens
        result = self.graph.invoke(
            initial,
            config={"run_name": f"gateway::{APPS[app_id]['name']}", "tags": [app_id, "ai-gateway-demo"]},
        )
        if not result.get("blocked"):
            self.outcomes[app_id] += 1
        return result

    def cost_per_outcome(self) -> list[dict]:
        """Cost-per-outcome, per app — the number leadership actually acts on.
        Cost-per-token is a finance-team metric; 'resolving a ticket now costs
        $X instead of $Y' is legible outside engineering."""
        rows = []
        for app_id, app in APPS.items():
            outcomes = self.outcomes[app_id]
            spend = self.spend[app_id]
            baseline = self.baseline_by_app[app_id]
            rows.append({
                "app": app["name"],
                "outcome_label": app["outcome_label"],
                "outcomes": outcomes,
                "spend": round(spend, 4),
                "cost_per_outcome": round(spend / outcomes, 5) if outcomes else 0.0,
                "baseline_cost_per_outcome": round(baseline / outcomes, 5) if outcomes else 0.0,
            })
        return rows

    def summary(self) -> str:
        total_spend = sum(self.spend.values())
        savings_pct = (1 - total_spend / self.total_baseline) * 100 if self.total_baseline else 0
        backend = "real Claude models (ANTHROPIC_API_KEY detected)" if REAL_MODELS_ENABLED else "mocked models (no API key set)"
        lines = ["", "=" * 60, f"Gateway summary — backend: {backend}", "=" * 60]
        for app_id, spend in self.spend.items():
            lines.append(f"  {APPS[app_id]['name']:<26} ${spend:>7.4f} / ${APPS[app_id]['daily_budget']:.2f} budget")
        lines += [
            "-" * 60,
            f"  Requests:            {self.total_requests}",
            f"  Cache hit rate:      {self.cache_hits}/{self.total_requests} "
            f"({(self.cache_hits/self.total_requests*100 if self.total_requests else 0):.0f}%)",
            f"  Blocked by budget:   {self.blocked_count}",
            f"  Gateway spend:       ${total_spend:.4f}",
            f"  No-gateway baseline: ${self.total_baseline:.4f}",
            f"  Savings:             {savings_pct:.1f}%",
        ]
        return "\n".join(lines)

    @staticmethod
    def _cache_key(prompt: str) -> str:
        return hashlib.sha1(prompt.strip().lower().encode()).hexdigest()
