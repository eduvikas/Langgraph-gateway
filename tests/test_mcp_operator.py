"""Operator enforcement and token handling in the MCP adapter, called directly (no subprocess)."""
import pytest

pytest.importorskip("mcp")
import app.mcp_server as srv  # noqa: E402
from app.security.identity import IdentityError  # noqa: E402


@pytest.fixture
def local(monkeypatch):
    monkeypatch.delenv("MCP_GATEWAY_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ALLOW_INSECURE_LOCAL", "true")
    monkeypatch.setenv("MCP_DEV_USER_ID", "tester")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.delenv("MCP_DEV_ROLES", raising=False)


def test_default_local_identity_is_a_plain_developer(local):
    from app.mcp_auth import resolve_mcp_identity
    assert resolve_mcp_identity(None, "demo-app").roles == {"developer"}


def test_developer_is_denied_control_plane_tools(local):
    with pytest.raises(IdentityError, match="OPERATOR_ROLE_REQUIRED"):
        srv.gateway_get_usage("demo-app")
    with pytest.raises(IdentityError, match="OPERATOR_ROLE_REQUIRED"):
        srv.gateway_get_routing_decision("req_x", "demo-app")


def test_operator_role_unlocks_control_plane_tools(local, monkeypatch):
    monkeypatch.setenv("MCP_DEV_ROLES", "developer,operator")
    assert srv.gateway_get_usage("demo-app")["application_id"] == "demo-app"
    assert srv.gateway_get_routing_decision("req_missing", "demo-app") == {"found": False, "request_id": "req_missing"}


def test_non_control_plane_tools_work_for_a_developer(local):
    assert "limit_usd" in srv.gateway_check_budget("demo-app")


def test_dev_roles_are_ignored_when_a_bearer_token_is_supplied(monkeypatch):
    import app.mcp_auth as mcp_auth
    from types import SimpleNamespace
    from app.security.identity import Identity
    monkeypatch.setenv("MCP_DEV_ROLES", "admin")
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: SimpleNamespace(app_env="local", auth_enabled=True))
    monkeypatch.setattr(mcp_auth, "IdentityProvider", lambda _s: SimpleNamespace(
        authenticate=lambda *_: Identity("alice", {"viewer"}, {"demo-app"}, {})))
    assert mcp_auth.resolve_mcp_identity("Bearer t", "demo-app").roles == {"viewer"}


@pytest.mark.parametrize("env_value", ["abc.def.ghi", "Bearer abc.def.ghi", "bearer abc.def.ghi", "  abc.def.ghi  "])
def test_bare_or_prefixed_stdio_token_is_normalised(monkeypatch, env_value):
    monkeypatch.setenv("MCP_GATEWAY_BEARER_TOKEN", env_value)
    assert srv._authorization(None).lower() == "bearer abc.def.ghi"


def test_no_token_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv("MCP_GATEWAY_BEARER_TOKEN", raising=False)
    assert srv._authorization(None) is None
