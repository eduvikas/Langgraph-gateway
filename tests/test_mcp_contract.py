"""Static contract checks for the MCP adapter; runtime protocol tests need `mcp` installed."""
import ast
from pathlib import Path


def test_expected_mcp_tools_are_declared():
    source = Path("app/mcp_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and isinstance(d.func.value, ast.Name) and d.func.value.id == "mcp"
                   and d.func.attr == "tool" for d in node.decorator_list):
                tools.add(node.name)
    assert tools == {
        "gateway_chat", "gateway_estimate_cost", "gateway_check_budget",
        "gateway_get_routing_decision", "gateway_get_usage", "gateway_health"
    }


def test_remote_transport_is_explicitly_disabled_until_secure_auth_is_ready():
    source = Path("app/mcp_server.py").read_text(encoding="utf-8")
    assert "per-client OAuth/JWT verification and TLS" in source
    assert 'if transport != "stdio"' in source


def _function_calls(name):
    tree = ast.parse(Path("app/mcp_server.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    raise AssertionError(f"{name} not found")


def test_control_plane_tools_require_operator_and_other_tools_do_not():
    assert "_operator_identity" in _function_calls("gateway_get_usage")
    assert "_operator_identity" in _function_calls("gateway_get_routing_decision")
    for name in ("gateway_chat", "gateway_estimate_cost", "gateway_check_budget", "gateway_health"):
        assert "_operator_identity" not in _function_calls(name)
    assert "require_mcp_operator" in _function_calls("_operator_identity")


def test_no_dynamic_import_tricks():
    assert "__import__" not in Path("app/mcp_server.py").read_text(encoding="utf-8")
