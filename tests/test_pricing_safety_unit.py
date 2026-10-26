from app.config import Settings
from app.economics.accounting import economics_block
from app.economics.pricing import price_call


def test_unknown_real_model_has_no_fabricated_baseline_savings():
    result = price_call(Settings(), "openai", "unlisted-real-model", 1000, 500)
    assert result.billable is True
    assert result.priced is False
    assert result.cost_usd == 0.0
    assert result.baseline_cost_usd == 0.0
    economics = economics_block({"cost_usd": result.cost_usd, "baseline_cost_usd": result.baseline_cost_usd,
                                 "priced": result.priced})
    assert economics["cost_usd"] is None
    assert economics["baseline_cost_usd"] is None
    assert economics["savings_usd"] is None


def test_unknown_baseline_does_not_claim_priced_savings():
    settings = Settings(baseline_model="unlisted-baseline")
    result = price_call(settings, "openai", "gpt-5.6-luna", 1000, 500)
    assert result.priced is False
