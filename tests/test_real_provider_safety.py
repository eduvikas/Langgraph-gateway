"""The real-provider preflight must fail on every configuration mistake that could cost money, spend nothing itself,
and the GPT-6 configuration template must run end to end through the gateway (with a simulated OpenAI response)."""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".env.real-provider.example"
TODAY = datetime.date.today().isoformat()


def system_env(home):
    """Minimal environment for a child Python process. Windows needs SYSTEMROOT (and friends) or Python cannot start."""
    keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
    return {**{k: os.environ[k] for k in keep if k in os.environ}, "HOME": str(home), "GATEWAY_IGNORE_DOTENV": "1"}



def template_env():
    env = {}
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    return env


def good_env(tmp_path):
    env = template_env()
    env["OPENAI_API_KEY"] = "sk-proj-TESTONLYNOTREAL0123456789"
    env["MODEL_PRICING_JSON"] = env["MODEL_PRICING_JSON"].replace("REPLACE_WITH_DATE_YOU_CHECKED", TODAY)
    env["POLICY_FILE"] = str(ROOT / env["POLICY_FILE"])
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'real.db'}"
    return env


def write_env(env, tmp_path):
    p = tmp_path / "test.env"
    p.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
    return p


def preflight(env, tmp_path):
    proc = subprocess.run([sys.executable, "scripts/preflight_real_provider.py", "--env-file", str(write_env(env, tmp_path))],
                          cwd=ROOT, capture_output=True, text=True, env=system_env(tmp_path))
    return proc.returncode, proc.stdout


def test_shipped_template_is_refused_until_the_human_fills_it_in(tmp_path):
    env = template_env(); env["POLICY_FILE"] = str(ROOT / env["POLICY_FILE"])
    rc, out = preflight(env, tmp_path)
    assert rc == 1
    assert "OPENAI_API_KEY is empty or still a placeholder" in out and "verified_on must be the date YOU checked" in out


def test_filled_template_passes_and_never_prints_the_key(tmp_path):
    env = good_env(tmp_path)
    rc, out = preflight(env, tmp_path)
    assert rc == 0, out
    assert env["OPENAI_API_KEY"] not in out and "No network call was made" in out


def stale(e):  e["MODEL_PRICING_JSON"] = e["MODEL_PRICING_JSON"].replace(TODAY, "2026-01-01")
def mockon(e): e["MOCK_PROVIDER_ENABLED"] = "true"
def lowest(e): e["BUDGET_OUTPUT_ESTIMATE_TOKENS"] = "200"
def noprofiles(e): e["MODEL_PROFILES_JSON"] = ""
def unpriced(e): e["ALLOWED_MODELS"] += ",gpt-future-x"
def nobaseline(e): e["BASELINE_MODEL"] = "gpt-unpriced"
def nokey(e): e["OPENAI_API_KEY"] = ""
def zeroprice(e): e["MODEL_PRICING_JSON"] = e["MODEL_PRICING_JSON"].replace('"input_per_1m":0.1', '"input_per_1m":0')


@pytest.mark.parametrize("mutate, expect", [
    (stale, "days ago"), (mockon, "MOCK_PROVIDER_ENABLED"), (lowest, "less than a reply can cost"), (noprofiles, "MODEL_PROFILES_JSON is empty"),
    (unpriced, "gpt-future-x: no entry"), (nobaseline, "BASELINE_MODEL"), (nokey, "OPENAI_API_KEY"), (zeroprice, "must be positive")])
def test_each_money_risk_is_caught(tmp_path, mutate, expect):
    env = good_env(tmp_path); mutate(env)
    rc, out = preflight(env, tmp_path)
    assert rc == 1 and expect in out.replace("\n", " ") or expect in out, out


def test_unlimited_budget_and_stray_model_in_policy_are_caught(tmp_path):
    pol = json.loads((ROOT / "config/policies.real-provider.example.json").read_text())
    pol["applications"]["demo-app"]["daily_budget_usd"] = 0
    p = tmp_path / "p.json"; p.write_text(json.dumps(pol))
    env = good_env(tmp_path); env["POLICY_FILE"] = str(p)
    rc, out = preflight(env, tmp_path)
    assert rc == 1 and "UNLIMITED" in out
    pol["applications"]["demo-app"].update(daily_budget_usd=1, allowed_models=["gpt-6-luna", "gpt-9-secret"])
    p.write_text(json.dumps(pol))
    rc, out = preflight(env, tmp_path)
    assert rc == 1 and "gpt-9-secret" in out


SIM = """
import sys
sys.path.insert(0, "scripts")
from app.providers.base import LLMProvider, ModelResponse
import live_gateway_check as live
class OpenAISim(LLMProvider):
    def generate(self, prompt, history, model, max_output_tokens):
        return ModelResponse(text="OK", input_tokens=1000, output_tokens=200, total_tokens=1200, provider="openai", model=model)
sys.exit(live.main(sys.argv[1:], provider_factory=lambda settings, name="openai": OpenAISim()))
"""


def run_live(env, tmp_path, args):
    full = {**env, **system_env(tmp_path)}
    return subprocess.run([sys.executable, "-c", SIM, *args], cwd=ROOT, capture_output=True, text=True, env=full, timeout=120)


def test_live_check_refuses_without_confirm_and_when_preflight_fails(tmp_path):
    env = good_env(tmp_path)
    p = run_live(env, tmp_path, [])
    assert p.returncode == 2 and "Re-run with --confirm" in p.stdout
    env["BUDGET_OUTPUT_ESTIMATE_TOKENS"] = "100"
    p = run_live(env, tmp_path, ["--confirm"])
    assert p.returncode == 3 and "Not sending anything" in p.stdout


def test_gpt6_template_runs_end_to_end_and_costs_match_the_configured_prices(tmp_path):
    p = run_live(good_env(tmp_path), tmp_path, ["--confirm"])
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    assert "provider=openai model=gpt-6-luna" in p.stdout            # policy limited demo-app to the cheapest model
    assert "cost recorded by the gateway: $0.0002" in p.stdout            # 1000*0.10/1e6 + 200*0.50/1e6


def test_openai_error_codes_are_translated_into_plain_advice():
    sys.path.insert(0, str(ROOT / "scripts"))
    import live_gateway_check as live
    cases = {"ALL_MODELS_FAILED: Error code: 429 - {'error': {'code': 'project_spend_limit_exceeded'}}": "PROJECT hard spend limit",
             "ALL_MODELS_FAILED: Error code: 429 - {'error': {'code': 'organization_spend_limit_exceeded'}}": "ORGANIZATION hard spend limit",
             "Error code: 429 - {'error': {'code': 'credit_balance_exhausted'}}": "Prepaid credits",
             "Error code: 429 - organization_usage_limit_exceeded": "approved usage limit",
             "ALL_MODELS_FAILED: Error code: 401 - invalid": "wrong, revoked or expired",
             "Error code: 404 - model_not_found": "does not know that model ID"}
    for text, expect in cases.items():
        assert any(expect in advice for advice in live.diagnose(text)), text
    assert live.diagnose("something unrelated") == []


FAIL_SIM = SIM.replace('return ModelResponse(text="OK", input_tokens=1000, output_tokens=200, total_tokens=1200, provider="openai", model=model)',
                       'raise RuntimeError("Error code: 429 - {\'error\': {\'code\': \'project_spend_limit_exceeded\'}}")')


def test_live_check_explains_a_spend_limit_failure_without_a_traceback(tmp_path):
    full = {**good_env(tmp_path), **system_env(tmp_path)}
    p = subprocess.run([sys.executable, "-c", FAIL_SIM, "--confirm"], cwd=ROOT, capture_output=True, text=True, env=full, timeout=120)
    assert p.returncode == 1 and "Traceback" not in p.stderr
    assert "PROJECT hard spend limit" in p.stdout and "nothing further was sent" in p.stdout.lower()
    assert "rate limiting this key" not in p.stdout      # the specific code wins over the generic 429 hint
