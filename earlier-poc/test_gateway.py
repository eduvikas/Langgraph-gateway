"""Sanity tests for the control logic.   python -m unittest -v"""
import unittest

from gateway import config
from gateway.core import Features, Gateway, Request
from gateway.guardrails import redact

FULL = Features(routing=True, response_cache=True, prompt_cache=True, guardrails=True,
                budgets=True, breaker=True, fallback=True)


def req(i, app="hr-faq-bot", prompt="How many vacation days do I get", ts=100.0, cx="easy", **kw):
    return Request(i, ts, app, prompt, 1000, 100, 500, cx, **kw)


class GatewayTests(unittest.TestCase):
    def test_redaction(self):
        text, found = redact("mail jane@corp.example.com id EMP123456 key AKIAABCDEFGHIJKLMNOP")
        self.assertNotIn("jane", text)
        self.assertNotIn("EMP123456", text)
        self.assertNotIn("AKIA", text)
        self.assertEqual(sum(found.values()), 3)

    def test_residency_policy_blocks_us_models_for_hr(self):
        gw = Gateway(FULL)
        for i in range(200):   # even hard prompts must stay in allowed regions
            r = gw.handle(req(i, prompt=f"Analyze and compare the trade-off in package {i}", cx="hard", ts=i))
            self.assertIn(r["model"], ("self-hosted-oss", "mid-tier", "small-fast"))
            self.assertEqual(r["policy_violation"], 0)

    def test_circuit_breaker_stops_runaway_loop(self):
        gw = Gateway(FULL)
        out = [gw.handle(req(i, app="research-agent", prompt=f"Retry attempt {i}", cx="hard",
                             ts=i * 5, run_id="loop-1")) for i in range(40)]
        self.assertEqual(sum(r["status"] == "blocked" for r in out), 40 - config.MAX_CALLS_PER_RUN)

    def test_hard_budget_blocks(self):
        old = config.APPS["support-copilot"].daily_budget
        config.APPS["support-copilot"].daily_budget = 0.0001
        try:
            gw = Gateway(FULL)
            gw.handle(req(1, app="support-copilot", prompt="Draft a long reply about invoice one", cx="hard"))
            r = gw.handle(req(2, app="support-copilot", prompt="Analyze another ticket thread", cx="hard", ts=200))
            self.assertEqual(r["reason"], "budget_exhausted")
        finally:
            config.APPS["support-copilot"].daily_budget = old

    def test_paraphrase_hits_semantic_cache(self):
        gw = Gateway(FULL)
        gw.handle(req(1, prompt="How many vacation days do I get"))
        r = gw.handle(req(2, prompt="Hi, how many vacation days do I get please", ts=160))
        self.assertEqual(r["cache"], "semantic")
        self.assertEqual(r["cost"], 0.0)

    def test_pii_never_leaves_unredacted(self):
        gw = Gateway(FULL)
        r = gw.handle(req(1, app="support-copilot", prompt="Explain my invoice, email a@b.example.com", cx="medium",
                          has_pii=True))
        self.assertEqual(r["pii_external"], 0)
        self.assertEqual(r["pii_redactions"], 1)


if __name__ == "__main__":
    unittest.main()
