"""Model profiles (what the router can serve) and application policies (what is permitted) must agree."""
import json
import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.policy.store import PolicyStore
from app.routing.profiles import (DEFAULT_OPENAI_PROFILES, ModelConfigError, build_model_profiles,
                                  check_model_configuration, validate_model_configuration)
from tests.support import GPT_MODELS, GPT_PROFILES, build_graph, make_test_settings, write_policy_file

ROOT = Path(__file__).resolve().parent.parent


def report_for(tmp_path, settings=None, models=None, **per_app):
    settings = settings or make_test_settings()
    store = PolicyStore(write_policy_file(tmp_path, models, settings=settings, **per_app), settings)
    return validate_model_configuration(settings, build_model_profiles(settings), store)


def test_aligned_configuration_is_clean(tmp_path):
    r = report_for(tmp_path)
    assert r.errors == [] and r.warnings == []


def test_model_permitted_by_policy_but_unknown_to_the_router_is_reported(tmp_path):
    r = report_for(tmp_path, **{"demo-app": {"allowed_models": ["gpt-5.6-luna", "gpt-9-ghost"]}})
    assert r.ok and any("demo-app" in w and "gpt-9-ghost" in w for w in r.warnings)


def test_application_whose_models_are_all_unroutable_is_an_error(tmp_path):
    r = report_for(tmp_path, **{"demo-app": {"allowed_models": ["gpt-9-ghost"]}})
    assert not r.ok and "NO_ELIGIBLE_MODEL" in r.errors[0] and "demo-app" in r.errors[0]


def test_a_disabled_profile_counts_as_unavailable(tmp_path):
    profiles = [dict(p, enabled=p["model"] != "gpt-5.6-luna") for p in GPT_PROFILES]
    settings = make_test_settings(model_profiles_json=json.dumps(profiles))
    r = report_for(tmp_path, settings=settings, models=["gpt-5.6-luna"])
    assert not r.ok


def test_applications_without_an_explicit_list_use_the_global_allowlist(tmp_path):
    settings = make_test_settings(allowed_models_raw="gpt-9-ghost")
    path = tmp_path / "p.json"; path.write_text(json.dumps({"applications": {"demo-app": {}}}))
    r = validate_model_configuration(settings, build_model_profiles(settings), PolicyStore(str(path), settings))
    assert not r.ok and any("demo-app" in e for e in r.errors)


def test_enabled_profile_nobody_may_use_is_flagged(tmp_path):
    r = report_for(tmp_path, models=["gpt-5.6-luna", "gpt-5.6-terra"], settings=make_test_settings(allowed_models_raw="gpt-5.6-luna,gpt-5.6-terra"))
    assert any("gpt-5.6-sol" in w and "no application" in w for w in r.warnings)


def test_duplicate_profiles_and_unknown_capabilities_are_reported():
    settings = make_test_settings()
    profiles = build_model_profiles(settings) + build_model_profiles(settings)[:1]
    r = validate_model_configuration(settings, profiles)
    assert any("duplicate" in e for e in r.errors)
    odd = json.dumps([dict(GPT_PROFILES[0], capabilities=["general", "telepathy"])])
    r = validate_model_configuration(make_test_settings(model_profiles_json=odd), build_model_profiles(make_test_settings(model_profiles_json=odd)))
    assert any("telepathy" in w for w in r.warnings)


@pytest.mark.parametrize("raw,match", [("{not json", "not valid JSON"), ('{"a": 1}', "JSON list"), ('[{"model": "x"}]', "provider and model"),
                                       ('[{"provider": "openai", "model": "x", "capabilities": "general"}]', "list of strings")])
def test_malformed_profiles_fail_with_a_clear_error(raw, match):
    with pytest.raises(ModelConfigError, match=match):
        build_model_profiles(make_test_settings(model_profiles_json=raw))


def test_default_profiles_and_mock_fallback_are_unchanged():
    s = Settings(openai_api_key="sk-x", model_profiles_json="", mock_provider_enabled=True)
    assert [p.model for p in build_model_profiles(s)] == [d["model"] for d in DEFAULT_OPENAI_PROFILES] + ["mock-general"]
    assert build_model_profiles(Settings(openai_api_key="", model_profiles_json="", mock_provider_enabled=False)) == []


def test_shipped_policies_are_servable_by_the_default_profiles():
    """Only the mock model may be permitted-but-unroutable when a real key is configured; nothing may be an error."""
    settings = Settings(openai_api_key="sk-x", model_profiles_json="", mock_provider_enabled=False,
                        allowed_applications_raw="demo-app,contract-agent,sre-agent")
    r = validate_model_configuration(settings, build_model_profiles(settings), PolicyStore(str(ROOT / "config" / "policies.json"), settings))
    assert r.errors == []
    assert all("mock-general" in w for w in r.warnings), r.warnings


def test_production_refuses_an_unservable_configuration(monkeypatch, tmp_path):
    settings = make_test_settings(app_env="production", rate_limiter_backend="memory")
    policy = write_policy_file(tmp_path, **{"demo-app": {"allowed_models": ["gpt-9-ghost"]}})
    monkeypatch.setattr("app.gateway.graph.build_provider_health", lambda s: __import__("app.routing.router", fromlist=["x"]).ProviderHealth())
    with pytest.raises(ModelConfigError, match="NO_ELIGIBLE_MODEL"):
        build_graph(settings, policy)


def test_local_environments_log_instead_of_failing(tmp_path, caplog):
    settings = make_test_settings()
    store = PolicyStore(write_policy_file(tmp_path, **{"demo-app": {"allowed_models": ["gpt-9-ghost"]}}), settings)
    with caplog.at_level(logging.ERROR):
        report = check_model_configuration(settings, build_model_profiles(settings), store)
    assert not report.ok
    # The explanation itself must be in the message, not only in structured extras that a plain formatter drops.
    assert any("model_config_error" in r.getMessage() and "demo-app" in r.getMessage() and "gpt-9-ghost" in r.getMessage() for r in caplog.records)


def test_the_test_profiles_are_all_priced():
    from app.economics.pricing import PRICING
    assert set(GPT_MODELS) <= set(PRICING)


def test_a_required_capability_no_profile_has_blocks_cleanly_instead_of_crashing(tmp_path):
    settings = make_test_settings()
    graph, _, _ = build_graph(settings, write_policy_file(tmp_path, settings=settings))
    result = graph.invoke({"request_id": "r", "session_id": "s", "application_id": "demo-app", "user_id": "u",
                           "prompt": "describe this image", "authorization": "",
                           "routing_metadata": {"required_capabilities": ["vision"]}})
    assert result["decision"] == "BLOCK" and result["block_reason"] == "NO_ELIGIBLE_MODEL"
