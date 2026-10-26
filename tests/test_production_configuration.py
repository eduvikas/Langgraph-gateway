import json
import pytest
from app.config import Settings, validate_production_settings

def production_settings(**overrides):
    base = dict(
        app_env="production", auth_enabled=True, openai_api_key="sk-test-key-for-unit-tests", openai_model="model-a", jwt_secret="a-very-long-random-secret-value-for-tests",
        jwt_issuer="https://idp.company.com/issuer", jwt_audience="gateway", mock_provider_enabled=False,
        database_url="postgresql+psycopg://u:p@db/gateway", rate_limiter_backend="redis",
        cache_enabled=True, cache_backend="redis", memory_backend="sql",
        allowed_models_raw="model-a", baseline_model="model-a",
        model_pricing_json=json.dumps({"model-a": {"input_per_1m": 1.0, "output_per_1m": 2.0, "source": "https://platform.openai.com/docs/pricing", "verified_on": "2026-10-01"}}),
        model_profiles_json=json.dumps([{"provider":"openai", "model":"model-a", "quality":0.9, "latency":0.8, "capabilities":["general"]}]),
    )
    base.update(overrides)
    return Settings(**base)

def test_valid_production_configuration_passes():
    assert validate_production_settings(production_settings()) is True

def test_production_rejects_auth_disabled():
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        validate_production_settings(production_settings(auth_enabled=False))

def test_production_rejects_unverified_pricing_placeholder():
    prices = {"model-a": {"input_per_1m": 1.0, "output_per_1m": 2.0, "source": "https://platform.openai.com/docs/pricing", "verified_on": "YYYY-MM-DD"}}
    with pytest.raises(RuntimeError, match="verified_on must be YYYY-MM-DD"):
        validate_production_settings(production_settings(model_pricing_json=json.dumps(prices)))


def test_production_rejects_placeholder_api_key():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        validate_production_settings(production_settings(openai_api_key="REPLACE_WITH_SECRET_MANAGER_INJECTED_KEY"))

def test_production_rejects_non_finite_pricing():
    prices = {"model-a": {"input_per_1m": float("nan"), "output_per_1m": 2.0, "source": "https://platform.openai.com/docs/pricing", "verified_on": "2026-10-01"}}
    with pytest.raises(RuntimeError, match="invalid or non-finite token prices"):
        validate_production_settings(production_settings(model_pricing_json=json.dumps(prices)))


def test_production_rejects_placeholder_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_settings(production_settings(jwt_secret="REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS_FROM_SECRET_MANAGER"))

def test_production_rejects_placeholder_issuer():
    with pytest.raises(RuntimeError, match="JWT_ISSUER"):
        validate_production_settings(production_settings(jwt_issuer="https://your-identity-provider.example/issuer"))
