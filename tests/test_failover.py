"""Failover must report the model that actually answered, and must never land on
a model the application's policy does not allow.

The configuration is explicit (see tests/support.py): GPT profiles are declared, the policy file lives in tmp_path,
and settings do not read the environment - so a request can only be blocked by what the test itself sets up."""
import pytest

from tests.support import (GPT_PROFILES, build_graph, install_provider, make_test_settings, model_response,
                           write_policy_file)


def make_graph(monkeypatch, tmp_path, failing, policy_file=None, settings=None):
    settings = settings or make_test_settings()

    def generate(model, prompt, history):
        if model in failing:
            raise RuntimeError("simulated outage " + model)
        return model_response(model, f"answered by {model}")

    install_provider(monkeypatch, generate)
    graph, _, _ = build_graph(settings, policy_file or write_policy_file(tmp_path, settings=settings))
    return graph


def request(prompt="hello"):
    return {"request_id": "r1", "session_id": "s1", "application_id": "demo-app", "user_id": "u1",
            "prompt": prompt, "authorization": ""}


def test_fixture_declares_gpt_profiles_explicitly():
    settings = make_test_settings()
    assert {p["model"] for p in GPT_PROFILES} == {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
    assert settings.model_profiles_json and settings.allowed_applications == {"demo-app", "contract-agent", "sre-agent"}


def test_reports_the_model_that_actually_answered(monkeypatch, tmp_path):
    graph = make_graph(monkeypatch, tmp_path, failing={"gpt-5.6-luna"})   # luna is the top choice under 'balanced'
    result = graph.invoke(request())
    assert result["decision"] == "ALLOW", result.get("block_reason")      # not blocked before execution
    assert result["response"] == "answered by gpt-5.6-terra"
    assert result["selected_model"] == "gpt-5.6-terra"                    # used to say gpt-5.6-luna
    assert result["failed_models"] == ["gpt-5.6-luna"]


def test_no_failover_means_nothing_reported_as_failed(monkeypatch, tmp_path):
    result = make_graph(monkeypatch, tmp_path, failing=set()).invoke(request())
    assert result["decision"] == "ALLOW", result.get("block_reason")
    assert result["selected_model"] == "gpt-5.6-luna" and result["failed_models"] == []


def test_failover_never_uses_a_model_the_app_is_not_allowed(monkeypatch, tmp_path):
    policy = write_policy_file(tmp_path, **{"demo-app": {"allowed_models": ["gpt-5.6-luna"]}})
    graph = make_graph(monkeypatch, tmp_path, failing={"gpt-5.6-luna"}, policy_file=policy)
    with pytest.raises(RuntimeError, match="ALL_MODELS_FAILED"):
        graph.invoke(request())          # must NOT quietly fall over to terra or sol


def test_request_routing_hint_is_used_for_selection(monkeypatch, tmp_path):
    graph = make_graph(monkeypatch, tmp_path, failing=set())
    req = request("Debug this Python function and explain the stack trace")
    req["routing_metadata"] = {"task_type": "coding", "priority": "quality"}
    result = graph.invoke(req)
    assert result["decision"] == "ALLOW", result.get("block_reason")
    assert result["task_type"] == "coding"
    assert result["routing_priority"] == "quality"
    assert result["response"] == f"answered by {result['selected_model']}"
    assert result["selected_model"] in {"gpt-5.6-sol", "gpt-5.6-terra"}
