"""Guardrails: PII / secret redaction and the agent circuit breaker."""
import re
from collections import Counter, defaultdict

from .config import MAX_CALLS_PER_RUN, MAX_TOKENS_PER_RUN

PII_PATTERNS = [
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("EMP_ID", re.compile(r"\bEMP\d{6}\b")),
    ("PHONE", re.compile(r"\+?\d[\d\s-]{9,}\d")),
]


def redact(text):
    """Replace PII and secrets with placeholders. Returns (clean_text, Counter)."""
    found = Counter()
    for label, pattern in PII_PATTERNS:
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            found[label] += n
    return text, found


class CircuitBreaker:
    """Stops runaway agent loops: caps calls and tokens per run_id."""

    def __init__(self):
        self.calls = defaultdict(int)
        self.tokens = defaultdict(int)
        self.tripped_runs = set()

    def tripped(self, run_id):
        hit = self.calls[run_id] >= MAX_CALLS_PER_RUN or self.tokens[run_id] >= MAX_TOKENS_PER_RUN
        if hit:
            self.tripped_runs.add(run_id)
        return hit

    def record(self, run_id, tokens):
        self.calls[run_id] += 1
        self.tokens[run_id] += tokens
