"""Live gateway endpoint (stdlib only). Same control logic as the simulation, real HTTP.

    python server.py                      # http://localhost:8080
    curl -s localhost:8080/v1/chat -H 'Authorization: Bearer sk-hr-demo' \
         -d '{"prompt":"How many vacation days do I get? My email is jane@corp.example.com"}'
    curl -s localhost:8080/metrics
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

from gateway.config import APPS, KEY_TO_APP
from gateway.core import Features, Gateway, Request
from gateway.guardrails import redact
from gateway.router import classify

GW = Gateway(Features(routing=True, response_cache=True, prompt_cache=True, guardrails=True,
                      budgets=True, breaker=True, fallback=True), scenario="live")
LOCK, COUNTER = Lock(), [0]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {"ok": True})
        if self.path == "/metrics":
            with LOCK:
                per_app = {}
                for r in GW.results:
                    a = per_app.setdefault(r["app"], {"team": r["team"], "calls": 0, "spend_usd": 0.0,
                                                      "cache_hits": 0, "blocked": 0})
                    a["calls"] += 1
                    a["spend_usd"] = round(a["spend_usd"] + r["cost"], 6)
                    a["cache_hits"] += bool(r["cache"])
                    a["blocked"] += r["status"] == "blocked"
                return self._send(200, {"calls": len(GW.results), "by_app": per_app,
                                        "budgets_usd": {n: a.daily_budget for n, a in APPS.items()}})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat":
            return self._send(404, {"error": "not found"})
        key = self.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if key not in KEY_TO_APP:
            return self._send(401, {"error": "unknown API key"})
        app = APPS[KEY_TO_APP[key]]
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            prompt = str(body["prompt"])
        except (ValueError, KeyError):
            return self._send(400, {"error": 'send JSON like {"prompt": "..."}'})
        est_in = int(len(prompt.split()) * 1.3) + app.sys_tokens
        est_out = int(body.get("max_tokens", sum(app.out_tokens) // 2))
        with LOCK:
            COUNTER[0] += 1
            req = Request(COUNTER[0], time.time(), app.name, prompt, est_in, est_out, app.sys_tokens,
                          classify(prompt, est_in), run_id=body.get("run_id"), has_pii=bool(redact(prompt)[1]))
            rec = GW.handle(req)
        code = {"ok": 200, "blocked": 429, "error": 502}[rec["status"]]
        self._send(code, {"status": rec["status"], "reason": rec["reason"], "app": app.name, "team": app.team,
                          "model": rec["model"], "cache": rec["cache"] or "miss",
                          "predicted_difficulty": rec["complexity_pred"], "pii_redactions": rec["pii_redactions"],
                          "cost_usd": rec["cost"], "latency_ms": rec["latency_ms"],
                          "content": "[mock completion from %s]" % rec["model"] if rec["status"] == "ok" else None})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("AI gateway listening on http://localhost:8080  (keys:", ", ".join(KEY_TO_APP), ")")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
