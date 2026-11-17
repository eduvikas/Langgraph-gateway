import pytest

from app.routing.classifier import classify_request


def test_code_request_is_classified_as_coding():
    result = classify_request("Debug this Python function and explain the stack trace")
    assert result.task_type == "coding"
    assert result.estimated_complexity == "medium"


def test_reasoning_request_prefers_quality():
    result = classify_request("Prove this claim and compare trade-offs for the architecture decision")
    assert result.task_type == "reasoning"
    assert result.priority == "quality"


def test_short_greeting_prefers_low_latency():
    result = classify_request("Hi")
    assert result.task_type == "general_fast"
    assert result.priority == "latency"


def test_explicit_routing_hints_are_allowlisted():
    result = classify_request("Explain this", {"task_type": "coding", "priority": "cost", "required_capabilities": ["coding", "unknown"]})
    assert result.task_type == "coding"
    assert result.priority == "cost"
    assert result.required_capabilities == ("coding",)


def test_invalid_hints_fall_back_to_heuristics():
    result = classify_request("Debug this Python code", {"task_type": "malicious", "priority": "free"})
    assert result.task_type == "coding"
    assert result.priority == "balanced" or result.priority == "quality"


def test_cost_priority_accounts_for_input_and_output_prices():
    from app.routing.router import IntelligentRouter, ModelProfile
    router = IntelligentRouter([
        ModelProfile("p", "expensive-output", 0.1, 100.0, 0.9, 0.8, {"general"}),
        ModelProfile("p", "cheap-balanced", 1.0, 1.0, 0.8, 0.8, {"general"}),
    ])
    assert router.choose(priority="cost").model == "cheap-balanced"


def test_valid_capabilities_beyond_task_names_are_kept():
    """Capabilities are a wider vocabulary than task types: vision/embeddings/tool_calling must survive."""
    hints = {"required_capabilities": ["vision", "embeddings", "tool_calling", "json_mode", "mcp", "coding", "general_fast"]}
    result = classify_request("Explain this", hints)
    assert result.required_capabilities == ("coding", "embeddings", "general_fast", "json_mode", "mcp", "tool_calling", "vision")


def test_unknown_and_malformed_capabilities_are_still_dropped():
    assert classify_request("x", {"required_capabilities": ["vision", "root_access"]}).required_capabilities == ("vision",)
    assert classify_request("x", {"required_capabilities": "vision"}).required_capabilities == ()
    assert classify_request("x", {"required_capabilities": ["vision", 7]}).required_capabilities == ()


def test_required_capability_selects_only_models_that_have_it():
    from app.routing.router import IntelligentRouter, ModelProfile
    router = IntelligentRouter([
        ModelProfile("p", "text-only", 1, 1, 0.99, 0.99, {"general"}),
        ModelProfile("p", "multimodal", 1, 1, 0.50, 0.50, {"general", "vision", "tool_calling"}),
    ])
    required = classify_request("x", {"required_capabilities": ["vision", "tool_calling"]}).required_capabilities
    assert router.choose(required_capabilities=required).model == "multimodal"
    with pytest.raises(RuntimeError, match="NO_HEALTHY_MODEL_AVAILABLE"):
        router.choose(required_capabilities=classify_request("x", {"required_capabilities": ["embeddings"]}).required_capabilities)
