"""Guards against configuring model IDs that don't exist at the provider.

A wrong ID doesn't fail loudly: the router ranks it first, the call errors, and
failover quietly answers from another model. Keep this list in step with
OpenAI's model page when you add or retire models.
"""
import json
import re
from pathlib import Path

from app.gateway.graph import PRICING

VALID_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra", "mock-general"}
ROOT = Path(__file__).resolve().parent.parent


def test_pricing_table_uses_valid_ids():
    assert set(PRICING) <= VALID_MODELS


def test_policy_file_uses_valid_ids():
    policies = json.loads((ROOT / "config" / "policies.json").read_text(encoding="utf-8"))
    for app_id, policy in policies["applications"].items():
        assert set(policy.get("allowed_models", [])) <= VALID_MODELS, app_id


def test_env_example_uses_valid_ids():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("ALLOWED_MODELS="):
            assert set(line.split("=", 1)[1].split(",")) <= VALID_MODELS
        if line.startswith("OPENAI_MODEL="):
            assert line.split("=", 1)[1] in VALID_MODELS


def test_default_allowed_models_use_valid_ids():
    from app.config import Settings
    assert Settings().allowed_models <= VALID_MODELS
