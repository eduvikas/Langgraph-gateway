"""
Feature-based request classifier + routing policy for the AI Gateway service.

This replaces the simulated complexity used in gateway_graph.py's demo
scripts with signals actually available on a live request: token count,
whether tools are attached, and the step number in an agent's loop. A
learned classifier (trained on real routing outcomes) is the natural next
step — this is the rule-based version it's meant to sit alongside, not a
finished replacement for it.
"""
from dataclasses import dataclass, field

TIER_ORDER = ["small", "mid", "frontier"]


class PolicyConflict(Exception):
    """Raised when the caller's own constraints are impossible to satisfy
    together — e.g. asking for at least the frontier tier on a request
    also flagged data-sensitive. The caller doesn't get a silent downgrade;
    they get a 403 telling them why."""


@dataclass
class RoutingDecision:
    tier: str
    complexity_score: float
    policy_override: bool = False
    capability_override: bool = False
    reasons: list = field(default_factory=list)


def estimate_tokens(text_parts: list) -> int:
    """Rough chars/4 estimate. Swap for a real tokenizer (tiktoken, the
    provider's own counting endpoint, etc.) in production — this is meant
    to be replaceable, not authoritative."""
    chars = sum(len(t or "") for t in text_parts)
    return max(1, chars // 4)


def score_complexity(token_count: int, step: int) -> float:
    """Complexity is about size and accumulated context alone. Whether
    tools are attached is a capability requirement, not a complexity
    signal — it's handled as its own override in decide_tier() below, so
    it stays visible instead of being folded invisibly into this score."""
    token_component = min(token_count / 6000, 1.0)
    step_component = min(step / 10, 1.0) * 0.15  # later loop steps carry more context
    return round(min(1.0, 0.85 * token_component + step_component), 3)


def decide_tier(
    text_parts: list,
    has_tools: bool = False,
    step: int = 0,
    data_sensitive: bool = False,
    explicit_tier: str | None = None,
    min_tier: str | None = None,
    max_tier: str | None = None,
) -> RoutingDecision:
    reasons = []
    token_count = estimate_tokens(text_parts)
    score = score_complexity(token_count, step)

    if explicit_tier:
        tier = explicit_tier
        reasons.append(f"model pinned explicitly to '{explicit_tier}' - skipping complexity scoring")
    else:
        if score < 0.30:
            tier = "small"
        elif score <= 0.70:
            tier = "mid"
        else:
            tier = "frontier"
        reasons.append(f"complexity_score={score} (tokens~{token_count}, tools={has_tools}, step={step}) -> {tier}")

    capability_override = False
    if has_tools and tier == "small":
        tier = "mid"
        capability_override = True
        reasons.append("tool calls requested - small tier isn't routed tool calls reliably, bumped to mid")

    # Policy override runs last and wins over everything, including an
    # explicit pin or a capability bump: compliance beats capability.
    policy_override = False
    if data_sensitive:
        if min_tier and TIER_ORDER.index(min_tier) > TIER_ORDER.index("small"):
            # The caller explicitly demanded at least mid/frontier on a
            # request also flagged sensitive — that's a real conflict, not
            # something to silently resolve. Surface it as a policy block.
            raise PolicyConflict(
                f"data_sensitive is set but min_tier='{min_tier}' was requested — "
                f"sensitive requests are restricted to the small, self-hosted tier."
            )
        if tier != "small":
            tier = "small"
            policy_override = True
            reasons.append("data_sensitive flag - forced to self-hosted small tier, overriding capability/complexity")
        if has_tools:
            reasons.append(
                "warning: tools were requested on a data-sensitive request — verify the "
                "self-hosted small-tier model actually supports the required tool schema"
            )

    if min_tier and TIER_ORDER.index(tier) < TIER_ORDER.index(min_tier):
        tier = min_tier
        reasons.append(f"min_tier='{min_tier}' enforced by caller")
    if max_tier and TIER_ORDER.index(tier) > TIER_ORDER.index(max_tier):
        tier = max_tier
        reasons.append(f"max_tier='{max_tier}' enforced by caller")

    return RoutingDecision(
        tier=tier, complexity_score=score, policy_override=policy_override,
        capability_override=capability_override, reasons=reasons,
    )
