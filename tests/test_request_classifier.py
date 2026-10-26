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
