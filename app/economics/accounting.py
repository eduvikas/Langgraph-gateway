"""Turns a finished pipeline result into a ledger row and the `usage` block of the response.

Kept out of the route so the same code path can be exercised in tests."""


def record_usage(ledger, *, request_id, request, result, default_model):
    blocked = result.get("decision") == "BLOCK"
    consumed = {"input_tokens": result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
                "total_tokens": result.get("total_tokens", 0)}
    ledger.record(
        request_id=request_id, user_id=result.get("user_id", request.user_id),
        application_id=request.application_id, session_id=request.session_id,
        provider=result.get("selected_provider", "openai"), model=result.get("selected_model", default_model),
        **consumed, decision=result.get("decision", "UNKNOWN"), status="blocked" if blocked else "success",
        cost_usd=result.get("cost_usd", 0.0), baseline_cost_usd=result.get("baseline_cost_usd", 0.0),
        avoided_cost_usd=result.get("avoided_cost_usd", 0.0), priced=bool(result.get("priced", True)), cache_hit=bool(result.get("cache_hit", False)),
        tokens_avoided=result.get("tokens_avoided", 0))
    return consumed


def economics_block(result):
    """Per-request economics shown to the caller."""
    cost, baseline = result.get("cost_usd", 0.0), result.get("baseline_cost_usd", 0.0)
    priced = bool(result.get("priced", True))
    return {"cost_usd": cost if priced else None, "baseline_cost_usd": baseline if priced else None,
            "savings_usd": round(baseline - cost, 8) if priced else None, "priced": priced,
            "cache_hit": bool(result.get("cache_hit", False)), "tokens_avoided": result.get("tokens_avoided", 0),
            "avoided_cost_usd": result.get("avoided_cost_usd", 0.0),
            "billable": result.get("billable", True),
            "cache_skipped": result.get("cache_skip")}
