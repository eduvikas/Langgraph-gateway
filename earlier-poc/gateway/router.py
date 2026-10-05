"""Smart router: predict task difficulty, then pick the cheapest model that is allowed
(data residency), has capacity (own GPUs) and meets the app's quality floor."""
from .config import BY_COST, MODELS

HARD_HINTS = ("analy", "refactor", "root cause", "concurren", "race condition", "trade-off", "synthesi",
              "indemnif", "forecast", "multi-step", "vulnerab", "design a", "debug", "conflicting", "investigate")
MED_HINTS = ("summar", "explain", "draft", "compare", "why", "troubleshoot", "walk me through",
             "step by step", "review")


def classify(prompt, in_tokens):
    """Cheap heuristic difficulty classifier. In production: a small model or trained classifier."""
    p = prompt.lower()
    score = 0
    if "```" in p:
        score += 1
    if any(h in p for h in HARD_HINTS):
        score += 2
    elif any(h in p for h in MED_HINTS):
        score += 1
    if score == 0 and in_tokens > 8000:
        score = 1
    return "hard" if score >= 2 else "medium" if score == 1 else "easy"


def pick_model(app, pred, soft, fleet, ts, tokens, enforce_region, exclude=(), mode="cheapest"):
    cands = []
    for name in BY_COST:
        m = MODELS[name]
        if name in exclude:
            continue
        if enforce_region and app.allowed_regions and m.region not in app.allowed_regions:
            continue
        if m.tier == "self" and not fleet.has_capacity(ts, tokens):
            continue
        cands.append(m)
    if not cands:
        return None
    level = pred or "medium"
    if mode == "fallback":
        return max(cands, key=lambda m: m.quality[level])
    ok = [m for m in cands if m.quality[level] >= app.min_quality]
    if soft:  # over 80% of budget: avoid the priciest tier if anything else qualifies
        ok = [m for m in ok if m.tier != "frontier"] or ok
    return ok[0] if ok else max(cands, key=lambda m: m.quality[level])
