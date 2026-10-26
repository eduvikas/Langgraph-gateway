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
    assert d["meta"]["provider_mode"] == "simulated provider; real gateway"
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
