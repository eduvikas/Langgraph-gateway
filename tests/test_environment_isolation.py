"""Test results must not depend on exported environment variables (shell profile, CI secrets, containers)."""
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import configuration_env_vars

ROOT = Path(__file__).resolve().parent.parent
HOSTILE = {
    "ALLOWED_APPLICATIONS": "someone-else", "ALLOWED_MODELS": "other-model", "BASELINE_MODEL": "gpt-5.6-luna",
    "MOCK_PRICING_MODEL": "gpt-5.6-sol", "DEFAULT_DAILY_BUDGET_USD": "0.0000001", "MODEL_PRICING_JSON": "{}",
    "MODEL_PROFILES_JSON": '[{"provider":"openai","model":"other-model","capabilities":["general"]}]',
    "RATE_LIMITER_BACKEND": "redis", "REDIS_URL": "redis://127.0.0.1:1/0", "APP_ENV": "production", "CACHE_ENABLED": "false",
    "OPENAI_API_KEY": "sk-from-the-shell", "MOCK_PROVIDER_ENABLED": "true", "POLICY_FILE": "/nonexistent/policies.json",
}


def test_configuration_variables_are_not_present_in_the_test_process():
    leaked = sorted(n for n in configuration_env_vars() if n in os.environ)
    assert leaked == []


def test_discovery_covers_the_variables_that_matter():
    assert set(HOSTILE) <= configuration_env_vars()


def test_pipeline_suites_pass_under_a_hostile_environment():
    env = {**os.environ, **HOSTILE}
    files = ["tests/test_failover.py", "tests/test_economics_costs.py", "tests/test_budgets.py", "tests/test_cache.py"]
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
