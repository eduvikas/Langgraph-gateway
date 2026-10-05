"""Mocked model catalogue, applications and policies.

Every price, volume and quality figure here is ILLUSTRATIVE. Replace them with your
real price sheet, app inventory and evaluation results before quoting any numbers.
"""
from dataclasses import dataclass


@dataclass
class Model:
    name: str
    tier: str            # self | small | mid | frontier
    region: str          # onprem | eu | us
    in_per_m: float      # USD per 1M input tokens
    out_per_m: float     # USD per 1M output tokens
    ttft_ms: float       # time to first token
    ms_per_token: float  # generation speed
    cached_discount: float   # share of price still paid for provider-cached input tokens
    quality: dict        # P(acceptable answer) by task difficulty


MODELS = {
    "self-hosted-oss": Model("self-hosted-oss", "self", "onprem", 0.0, 0.0, 300, 12, 1.0,
                             {"easy": 0.95, "medium": 0.88, "hard": 0.70}),
    "small-fast": Model("small-fast", "small", "eu", 0.15, 0.60, 200, 5, 0.10,
                        {"easy": 0.94, "medium": 0.82, "hard": 0.55}),
    "mid-tier": Model("mid-tier", "mid", "eu", 1.00, 3.00, 400, 9, 0.10,
                      {"easy": 0.96, "medium": 0.92, "hard": 0.80}),
    "frontier-large": Model("frontier-large", "frontier", "us", 5.00, 15.00, 700, 14, 0.10,
                            {"easy": 0.97, "medium": 0.96, "hard": 0.94}),
}
BY_COST = ["self-hosted-oss", "small-fast", "mid-tier", "frontier-large"]  # cheapest first
FRONTIER = "frontier-large"

# Own GPU fleet: fixed daily cost, finite throughput
FLEET = {"gpus": 1, "gpu_hour_usd": 2.50, "capacity_tokens_per_min": 10_000, "headroom": 0.85}
FLEET_DAILY_COST = FLEET["gpus"] * FLEET["gpu_hour_usd"] * 24

API_ERROR_RATE = 0.004        # share of external calls that fail (provider 5xx)
PROMPT_CACHE_TTL_S = 300      # provider-side prefix cache lifetime
CACHE_TTL_S = 3600            # gateway response cache lifetime
SEMANTIC_THRESHOLD = 0.80     # similarity needed for a semantic cache hit
GATEWAY_OVERHEAD_MS = 12
CACHE_HIT_MS = 8
MAX_CALLS_PER_RUN = 25        # circuit breaker: calls per agent run
MAX_TOKENS_PER_RUN = 250_000  # circuit breaker: tokens per agent run
SOFT_BUDGET = 0.80            # share of daily budget after which we route cheaper
RUNAWAY_RATE = 0.02           # share of agent runs that get stuck in a loop (the "bug")


@dataclass
class App:
    name: str
    team: str
    use_case: str
    unit: str                # business outcome
    api_key: str             # virtual key (one per app)
    volume: int              # calls per day (runs per day for agentic apps)
    mix: tuple               # share of easy / medium / hard tasks
    sys_tokens: int          # long, repeated system prompt
    user_tokens: tuple
    out_tokens: tuple
    repeat_rate: float       # share of prompts that are recurring questions
    cacheable: bool          # safe to serve from cache (stateless)?
    pii_rate: float          # share of prompts containing PII or secrets
    allowed_regions: tuple   # data residency policy (None = anywhere)
    min_quality: float       # quality floor the router must respect
    daily_budget: float      # USD per day
    agentic: bool = False
    calls_per_outcome: float = 1.0


APPS = {
    "support-copilot": App(
        "support-copilot", "Customer Care", "Agent assist for support tickets", "ticket resolved",
        "sk-support-demo", 6000, (0.60, 0.28, 0.12), 1200, (150, 700), (150, 400),
        0.35, True, 0.08, None, 0.90, 40.0, calls_per_outcome=2.0),
    "code-review-bot": App(
        "code-review-bot", "Engineering", "Automated pull request review", "PR reviewed",
        "sk-code-demo", 1500, (0.15, 0.35, 0.50), 800, (2500, 9000), (300, 1000),
        0.00, False, 0.03, None, 0.90, 60.0),
    "doc-summarizer": App(
        "doc-summarizer", "Legal Ops", "Contract and policy summaries", "document summarized",
        "sk-docs-demo", 800, (0.25, 0.55, 0.20), 500, (6000, 18000), (250, 800),
        0.08, True, 0.10, None, 0.90, 40.0),
    "hr-faq-bot": App(
        "hr-faq-bot", "People & Culture", "Employee HR questions", "question answered",
        "sk-hr-demo", 2500, (0.80, 0.17, 0.03), 900, (30, 200), (60, 250),
        0.55, True, 0.25, ("onprem", "eu"), 0.85, 10.0),
    "research-agent": App(
        "research-agent", "Strategy", "Multi-step market research agent", "research brief",
        "sk-research-demo", 600, (0.10, 0.35, 0.55), 1500, (1200, 3500), (400, 900),
        0.00, False, 0.0, None, 0.90, 120.0, agentic=True, calls_per_outcome=5.5),
}
KEY_TO_APP = {a.api_key: a.name for a in APPS.values()}
