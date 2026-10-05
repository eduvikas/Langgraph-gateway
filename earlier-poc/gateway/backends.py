"""Mock model backends and the own-GPU fleet capacity tracker."""
from collections import defaultdict

from .config import FLEET


def price(model, in_tokens, out_tokens, cached_in=0):
    billed = in_tokens - cached_in
    return (billed * model.in_per_m + cached_in * model.in_per_m * model.cached_discount
            + out_tokens * model.out_per_m) / 1_000_000


class Fleet:
    """Tokens-per-minute capacity of the self-hosted GPU cluster."""

    def __init__(self):
        self.minutes = defaultdict(int)

    def used(self, ts):
        return self.minutes[int(ts // 60)]

    def has_capacity(self, ts, tokens):
        return self.used(ts) + tokens <= FLEET["capacity_tokens_per_min"] * FLEET["headroom"]

    def utilization(self, ts):
        return min(1.0, self.used(ts) / FLEET["capacity_tokens_per_min"])

    def add(self, ts, tokens):
        self.minutes[int(ts // 60)] += tokens
