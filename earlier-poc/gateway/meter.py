"""Usage metering into SQLite: one row per model call, attributable to app, team and use case."""
import os
import sqlite3

COLUMNS = ["scenario", "req_id", "ts", "hour", "app", "team", "use_case", "run_id", "model", "tier",
           "in_tokens", "out_tokens", "cached_in", "cost", "list_cost", "latency_ms", "status", "reason",
           "cache", "complexity_true", "complexity_pred", "quality", "pii_in_prompt", "pii_redactions",
           "pii_external", "policy_violation", "wasted", "fallback"]


class Meter:
    def __init__(self, path):
        if os.path.exists(path):
            os.remove(path)
        self.conn = sqlite3.connect(path)
        self.conn.execute(f"CREATE TABLE usage ({', '.join(COLUMNS)})")
        self.conn.execute("""CREATE VIEW v_cost_by_app AS
            SELECT scenario, app, team, COUNT(*) calls, ROUND(SUM(cost),2) cost_usd,
                   ROUND(SUM(list_cost),2) list_cost_usd
            FROM usage GROUP BY scenario, app""")
        self.conn.execute("""CREATE VIEW v_cost_by_model AS
            SELECT scenario, model, COUNT(*) calls, SUM(in_tokens+out_tokens) tokens, ROUND(SUM(cost),2) cost_usd
            FROM usage WHERE status='ok' GROUP BY scenario, model""")
        self.buf = []

    def log(self, rec):
        self.buf.append(tuple(rec.get(c) for c in COLUMNS))

    def flush(self):
        marks = ",".join("?" * len(COLUMNS))
        self.conn.executemany(f"INSERT INTO usage VALUES ({marks})", self.buf)
        self.conn.commit()
        self.buf = []
