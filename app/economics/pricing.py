"""Pricing and cost arithmetic.

All prices are USD per 1M tokens as (input, output). Re-check them against your provider's
pricing page before relying on cost figures, and keep them in one place: this table.
"""
from dataclasses import dataclass
import json
import os
from dotenv import load_dotenv
load_dotenv()

# Built-in rates are demo fixtures, not a claim about current provider prices. Production
# must supply MODEL_PRICING_JSON with a source URL/name and verification date per model.
PRICING = {
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.20, 1.20),
    "mock-general": (0, 0),
}
_PRICING_METADATA = {}
try:
    _configured = json.loads(os.getenv("MODEL_PRICING_JSON", "") or "{}")
    for _model, _entry in _configured.items():
        PRICING[_model] = (float(_entry["input_per_1m"]), float(_entry["output_per_1m"]))
        _PRICING_METADATA[_model] = {"source": _entry.get("source"), "verified_on": _entry.get("verified_on")}
except (ValueError, TypeError, KeyError):
    # Production configuration validation raises a useful error at startup.
    pass



@dataclass(frozen=True)
class CostBreakdown:
    cost_usd: float            # what this call cost
    baseline_cost_usd: float   # what the same tokens would have cost on the baseline model
    billable: bool             # False for the mock provider unless MOCK_PRICING_MODEL is set
    priced: bool               # False if a real model has no entry in PRICING (cost then reads 0)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICING.get(model, (0, 0))
    return round(input_tokens * in_price / 1_000_000 + output_tokens * out_price / 1_000_000, 8)


def price_call(settings, provider: str, model: str, input_tokens: int, output_tokens: int) -> CostBreakdown:
    """Cost of a call and the baseline it is compared with.

    Real providers are billed at their own model's price. The mock provider is free, so counting
    it against an expensive baseline would report a fake 100% saving: it is left unbilled unless
    MOCK_PRICING_MODEL names a real model to price it as (useful for demos)."""
    billed_model = (settings.mock_pricing_model or None) if provider == "mock" else model
    if not billed_model:
        return CostBreakdown(0.0, 0.0, billable=False, priced=True)
    if billed_model not in PRICING or settings.baseline_model not in PRICING:
        # Do not manufacture savings when either side of the comparison is unpriced.
        return CostBreakdown(0.0, 0.0, billable=True, priced=False)
    return CostBreakdown(
        cost_usd=cost_usd(billed_model, input_tokens, output_tokens),
        baseline_cost_usd=cost_usd(settings.baseline_model, input_tokens, output_tokens),
        billable=True,
        priced=True,
    )
