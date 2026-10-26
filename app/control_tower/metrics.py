from datetime import datetime, timedelta, timezone


def _ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


class ControlTower:
    def __init__(self, usage_ledger, evaluation_store, health, budget=None):
        self.usage = usage_ledger; self.evals = evaluation_store; self.health = health; self.budget = budget

    def snapshot(self):
        """All-time figures, computed in SQL (the old version summed only the latest 1000 events)."""
        t = self.usage.totals()
        ev = self.evals.recent(1000)
        avg = round(sum(x.get('overall', 0) for x in ev) / len(ev), 3) if ev else None
        by_model = {f"{r['provider']}:{r['model']}": {'requests': r['requests'], 'tokens': r['tokens'], 'cost_usd': r['cost_usd'], 'unpriced_requests': r.get('unpriced_requests', 0)}
                    for r in self.usage.by_model()}
        return {'requests': t['requests'], 'successful_requests': t['successful'], 'blocked_requests': t['blocked'], 'unpriced_requests': t.get('unpriced_requests', 0),
                'total_tokens': t['tokens'], 'total_cost_usd': t['cost_usd'], 'baseline_cost_usd': t['baseline_cost_usd'],
                'savings_usd': round(t['baseline_cost_usd'] - t['cost_usd'], 8),
                'cache_hits': t['cache_hits'], 'cache_hit_rate': _ratio(t['cache_hits'], t['successful']),
                'evaluation_count': len(ev), 'average_evaluation_score': avg,
                'by_model': by_model, 'provider_health': self.health.snapshot()}

    def economics(self, days=1):
        """Cost, savings and budget position for the last `days` days (1 = since 00:00 UTC today)."""
        now = datetime.now(timezone.utc)
        since = self.usage.utc_day_start(now) - timedelta(days=max(days, 1) - 1)
        t = self.usage.totals(since=since)
        savings = round(t['baseline_cost_usd'] - t['cost_usd'], 8)
        cache_savings = t['avoided_cost_usd']
        apps = []
        for row in self.usage.by_application(since=since):
            app = {**row, 'savings_usd': round(row['baseline_cost_usd'] - row['cost_usd'], 8),
                   'cache_hit_rate': _ratio(row['cache_hits'], row['successful'])}
            if self.budget is not None:
                app['budget'] = self.budget.status(row['application_id'])
            apps.append(app)
        return {'period': {'since': since.isoformat(), 'days': max(days, 1)},
                'totals': {**t, 'savings_usd': savings, 'savings_pct': _ratio(savings, t['baseline_cost_usd']),
                           'savings_from_cache_usd': round(cache_savings, 8),
                           'savings_from_model_choice_usd': round(savings - cache_savings, 8),
                           'cache_hit_rate': _ratio(t['cache_hits'], t['successful'])},
                'by_application': apps,
                'by_model': self.usage.by_model(since=since),
                'baseline': 'the same tokens priced on the baseline model (BASELINE_MODEL)'}
