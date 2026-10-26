"""Deterministic request classification for gateway routing.

This intentionally uses transparent heuristics, not a claim of semantic understanding.
Clients may provide explicit routing metadata; invalid values are ignored in favour
of conservative inference. Enterprise deployments should replace/augment these
rules with evaluated classifiers and policy-approved overrides.
"""
from dataclasses import dataclass

VALID_TASKS = {"general", "reasoning", "coding", "general_fast"}
VALID_PRIORITIES = {"balanced", "quality", "latency", "cost"}

@dataclass(frozen=True)
class RequestClassification:
    task_type: str
    priority: str
    required_capabilities: tuple[str, ...]
    estimated_complexity: str
    reason: str


def classify_request(prompt: str, metadata: dict | None = None) -> RequestClassification:
    metadata = metadata or {}
    text = (prompt or "").lower()
    # Explicit client hints are accepted only from a small allowlist.
    task = metadata.get("task_type")
    priority = metadata.get("priority")
    required = metadata.get("required_capabilities", [])
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        required = []
    required = tuple(sorted(set(required) & VALID_TASKS))

    reasons = []
    if task not in VALID_TASKS:
        if any(k in text for k in ("debug", "python", "code", "function", "stack trace", "compile", "sql query")):
            task = "coding"; reasons.append("coding keywords")
        elif any(k in text for k in ("prove", "derive", "reason step", "compare trade-offs", "root cause", "architecture decision", "formal proof")):
            task = "reasoning"; reasons.append("reasoning keywords")
        elif len(prompt or "") < 180 and any(k in text for k in ("hello", "hi", "thanks", "what time", "define ")):
            task = "general_fast"; reasons.append("short/simple request heuristic")
        else:
            task = "general"; reasons.append("default general task")
    else:
        reasons.append("client task hint")

    if priority not in VALID_PRIORITIES:
        if task == "reasoning": priority = "quality"
        elif task == "general_fast": priority = "latency"
        else: priority = "balanced"
        reasons.append("priority inferred from task")
    else:
        reasons.append("client priority hint")

    n = len(prompt or "")
    complexity = "high" if task == "reasoning" or n > 6000 else ("medium" if task == "coding" or n > 1500 else "low")
    return RequestClassification(task, priority, required, complexity, "; ".join(reasons))
