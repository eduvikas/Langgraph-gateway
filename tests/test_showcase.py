"""The leadership dashboard must stay a faithful picture of a real gateway run."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHOW = ROOT / "showcase"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))


def reconcile(d):
    """Python mirror of the proof panel in the page. Returns {check: bool}."""
    led = {r["request_id"]: r for r in d["ledger"]}
    aud = {r["request_id"] for r in d["audit"]}
    reqs = d["requests"]
    cost = lambda r: led.get(r["request_id"], {}).get("cost_usd", 0.0)
    blocked = [r for r in reqs if r["decision"] == "BLOCK"]
    return {
        "records": all(r["request_id"] in led and r["request_id"] in aud for r in reqs),
        "total": abs(sum(cost(r) for r in reqs) - d["economics"]["totals"]["cost_usd"]) < 1e-6,
        "blocked_free": all(cost(r) == 0 and not r["model"] for r in blocked),
        "budget_matches": all(abs(sum(cost(r) for r in reqs if r["app"] == a) - b["spent_today_usd"]) < 1e-6 for a, b in d["budgets"].items()),
        "within_limits": all(b["spent_today_usd"] <= b["limit_usd"] + 1e-9 for b in d["budgets"].values()),
        "cache_free": all(cost(r) == 0 for r in reqs if r["cache_hit"]),
    }


def test_committed_run_data_reconciles():
    d = json.loads((SHOW / "run-data.json").read_text(encoding="utf-8"))
    assert all(reconcile(d).values()), reconcile(d)
    assert d["meta"]["provider_mode"] in ("simulated provider; real gateway", "real OpenAI provider; real gateway")
    metered = {r["provider"] for r in d["ledger"] if r["cost_usd"] > 0}
    assert metered == {"openai" if d["meta"]["live"] else "simulated"}
    assert {r["decision"] for r in d["requests"]} == {"ALLOW", "BLOCK"}


def test_page_embeds_exactly_the_committed_data_and_is_self_contained():
    html = (SHOW / "ai-gateway-showcase.html").read_text(encoding="utf-8")
    blob = re.search(r'<script type="application/json" id="d">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</")
    assert json.loads(blob) == json.loads((SHOW / "run-data.json").read_text(encoding="utf-8")), "rebuild: python scripts/build_showcase.py"
    assert "__DATA__" not in html
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html), "page must not load external resources"
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|sessionStorage", html)


def test_page_script_is_valid_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    html = (SHOW / "template.html").read_text(encoding="utf-8")
    js = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    tmp = SHOW / ".syntax-check.js"
    tmp.write_text(js, encoding="utf-8")
    try:
        proc = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
    finally:
        tmp.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr


def test_quick_regeneration_runs_the_real_gateway_and_reconciles(tmp_path):
    out = tmp_path / "run.json"
    proc = subprocess.run([sys.executable, "scripts/run_showcase.py", "--quick", "--out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    d = json.loads(out.read_text(encoding="utf-8"))
    assert all(reconcile(d).values()), reconcile(d)
    assert {"PROMPT_INJECTION_DETECTED", "SECRET_DETECTED", "APPLICATION_NOT_ALLOWED"} <= {r["reason"] for r in d["requests"] if r["decision"] == "BLOCK"}
    from build_showcase import build
    page = build(out, tmp_path / "page.html")
    assert page.stat().st_size > 20_000


import os  # noqa: E402

from test_real_provider_safety import good_env, system_env  # noqa: E402

SNIP = """
import sys
sys.path.insert(0, "scripts")
import run_showcase


def factory(settings, name="openai"):
    from app.providers.base import LLMProvider, ModelResponse

    class P(LLMProvider):
        def generate(self, prompt, history, model, max_output_tokens):
            n = max(1, len(prompt) // 4)
            return ModelResponse(text="ok", input_tokens=n, output_tokens=150, total_tokens=n + 150, provider="openai", model=model)
    return P()


sys.exit(run_showcase.main(sys.argv[1:], provider_factory=factory))
"""


def run_live(tmp_path, args, **env_over):
    env = {**good_env(tmp_path), **env_over, **system_env(tmp_path)}
    return subprocess.run([sys.executable, "-c", SNIP, *args], cwd=ROOT, capture_output=True, text=True, env=env, timeout=240)


def test_live_mode_refuses_without_explicit_spend_confirmation(tmp_path):
    p = run_live(tmp_path, ["--live"])
    assert p.returncode == 2 and "--confirm-spend" in p.stdout


def test_live_mode_stops_when_the_preflight_fails(tmp_path):
    p = run_live(tmp_path, ["--live", "--confirm-spend"], OPENAI_API_KEY="")
    assert p.returncode == 3 and "[FAIL]" in p.stdout and "Not sending anything" in p.stdout


def test_live_mode_refuses_when_worst_case_exceeds_the_cap(tmp_path):
    p = run_live(tmp_path, ["--live", "--confirm-spend", "--quick", "--max-usd", "0.001"])
    assert p.returncode == 4 and "worst case exceeds --max-usd" in p.stdout


def test_live_mode_end_to_end_with_a_simulated_openai_reply(tmp_path):
    out = tmp_path / "live.json"
    p = run_live(tmp_path, ["--live", "--confirm-spend", "--quick", "--max-usd", "5", "--out", str(out)])
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["meta"]["live"] is True and d["meta"]["provider_mode"] == "real OpenAI provider; real gateway"
    assert d["meta"]["preflight"]["FAIL"] == 0
    assert all(reconcile(d).values()), reconcile(d)
    assert {r["provider"] for r in d["ledger"] if r["cost_usd"] > 0} == {"openai"}
    assert sum(r["cost_usd"] for r in d["ledger"]) <= d["meta"]["worst_case_usd"]
    assert d["meta"]["max_output_tokens"] == d["meta"]["budget_output_estimate_tokens"] == 800
    assert {"PROMPT_INJECTION_DETECTED", "SECRET_DETECTED"} <= {r["reason"] for r in d["requests"] if r["decision"] == "BLOCK"}
    assert not any(r["failed_over_from"] for r in d["requests"])          # no scripted outage against a real provider


def test_simulated_run_ignores_a_real_provider_env_file(tmp_path):
    """Regression: running the simulated scenario with the real-provider .env loaded leaked BASELINE_MODEL and token
    caps into the run, which priced the baseline at real rates and showed negative savings."""
    out = tmp_path / "sim.json"
    env = {**good_env(tmp_path), **system_env(tmp_path)}
    p = subprocess.run([sys.executable, "scripts/run_showcase.py", "--quick", "--out", str(out)], cwd=ROOT, capture_output=True, text=True, env=env, timeout=240)
    assert p.returncode == 0, p.stdout[-1200:] + p.stderr[-1200:]
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["meta"]["live"] is False and d["meta"]["baseline_model"] == "gpt-5.6-sol"
    assert d["meta"]["max_output_tokens"] == 2000 and d["meta"]["budget_output_estimate_tokens"] == 500
    t = d["economics"]["totals"]
    assert t["baseline_cost_usd"] >= t["cost_usd"], t                       # the premium baseline can never be cheaper than what was served
    assert all(reconcile(d).values()), reconcile(d)
