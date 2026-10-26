"""Per-application daily budgets in USD, checked before each model call.

The limit comes from the application's policy (`daily_budget_usd` in config/policies.json) or,
failing that, DEFAULT_DAILY_BUDGET_USD; 0 or unset means unlimited. SQL-backed atomic reservations
coordinate admission across workers sharing the same database. Actual provider cost is reconciled
when the call completes. This prevents concurrent requests from all reserving the same remaining
budget, but cannot guarantee a strict dollar ceiling if actual usage exceeds the preflight estimate.
"""
from app.economics.pricing import price_call
from app.economics.reservations import SQLBudgetReservations

class UnpricedModelError(ValueError):
    """Raised when a budgeted request targets a model without a known price."""



def estimate_tokens(text):
    return max(1, len(text or "") // 4)


class BudgetService:
    def __init__(self, settings, policy_store, ledger):
        self.settings, self.policies, self.ledger = settings, policy_store, ledger
        self.reservations = SQLBudgetReservations(settings.database_url, ledger, lease_seconds=max(900, int(settings.request_timeout_seconds) + 120))

    def limit_for(self, application_id):
        """The daily limit in USD, or None when the application is unlimited."""
        limit = self.policies.get(application_id).daily_budget_usd
        if limit is None:
            limit = self.settings.default_daily_budget_usd
        return float(limit) if limit and limit > 0 else None

    def status(self, application_id):
        limit = self.limit_for(application_id)
        reservation = self.reservations.status(application_id)
        spent = reservation["spent_usd"]
        reserved = reservation["reserved_usd"]
        if limit is None:
            return {"limit_usd": None, "spent_today_usd": spent, "reserved_usd": reserved, "remaining_usd": None, "utilization": None,
                    "alert": False, "unlimited": True}
        utilization = round((spent + reserved) / limit, 4)
        return {"limit_usd": limit, "spent_today_usd": spent, "reserved_usd": reserved, "remaining_usd": round(max(limit - spent - reserved, 0.0), 8),
                "utilization": utilization, "alert": utilization >= self.settings.budget_alert_threshold, "unlimited": False}

    def estimate_breakdown(self, provider, model, prompt, history):
        """Return a pre-call estimate using prompt/history estimates and configured output allowance."""
        tokens_in = estimate_tokens(prompt) + sum(estimate_tokens(h.get("content", "")) for h in history)
        tokens_out = min(self.settings.max_output_tokens, self.settings.budget_output_estimate_tokens)
        return price_call(self.settings, provider, model, tokens_in, tokens_out)

    def estimate_cost(self, provider, model, prompt, history):
        """Compatibility helper returning the estimated USD cost."""
        return self.estimate_breakdown(provider, model, prompt, history).cost_usd

    def check(self, application_id, estimated_cost):
        """(allowed, status). Blocks when spend so far plus this request's estimate would pass the limit."""
        status = self.status(application_id)
        if status["unlimited"]:
            return True, status
        return status["spent_today_usd"] + status.get("reserved_usd", 0.0) + estimated_cost <= status["limit_usd"], status

    def reserve(self, application_id, request_id, estimated_cost):
        limit = self.limit_for(application_id)
        if limit is None:
            return True, self.status(application_id)
        allowed = self.reservations.reserve(application_id, request_id, estimated_cost, limit)
        return allowed, self.status(application_id)

    def settle(self, request_id, actual_cost):
        return self.reservations.settle(request_id, actual_cost)

    def release(self, request_id):
        return self.reservations.release(request_id)
