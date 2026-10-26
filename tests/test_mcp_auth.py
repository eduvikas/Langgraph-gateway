"""Focused MCP authentication and application-scope tests; no MCP SDK needed."""
from types import SimpleNamespace
import pytest

import app.mcp_auth as mcp_auth
from app.security.identity import Identity, IdentityError


def settings(**overrides):
    values = dict(app_env="local", auth_enabled=True)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_token_rejected_by_default(monkeypatch):
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: settings())
    monkeypatch.delenv("MCP_ALLOW_INSECURE_LOCAL", raising=False)
    with pytest.raises(IdentityError, match="MCP_BEARER_TOKEN_REQUIRED"):
        mcp_auth.resolve_mcp_identity(None, "demo-app")


def test_local_insecure_mode_requires_explicit_opt_in_and_user(monkeypatch):
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: settings(auth_enabled=False))
    monkeypatch.setenv("MCP_ALLOW_INSECURE_LOCAL", "true")
    monkeypatch.delenv("MCP_DEV_USER_ID", raising=False)
    with pytest.raises(IdentityError, match="MCP_DEV_USER_ID_REQUIRED"):
        mcp_auth.resolve_mcp_identity(None, "demo-app")


def test_local_insecure_mode_rejected_in_production(monkeypatch):
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: settings(app_env="production", auth_enabled=False))
    monkeypatch.setenv("MCP_ALLOW_INSECURE_LOCAL", "true")
    monkeypatch.setenv("MCP_DEV_USER_ID", "local-user")
    with pytest.raises(IdentityError, match="MCP_BEARER_TOKEN_REQUIRED"):
        mcp_auth.resolve_mcp_identity(None, "demo-app")


def test_application_scope_is_enforced(monkeypatch):
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: settings())
    monkeypatch.setattr(mcp_auth, "IdentityProvider", lambda _settings: SimpleNamespace(
        authenticate=lambda _auth, _user, _app: Identity("alice", {"viewer"}, {"app-a"}, {"sub": "alice"})
    ))
    with pytest.raises(IdentityError, match="APPLICATION_NOT_ASSIGNED"):
        mcp_auth.resolve_mcp_identity("Bearer signed-token", "app-b")


def test_wildcard_application_scope_is_allowed(monkeypatch):
    monkeypatch.setattr(mcp_auth, "get_settings", lambda: settings())
    monkeypatch.setattr(mcp_auth, "IdentityProvider", lambda _settings: SimpleNamespace(
        authenticate=lambda _auth, _user, _app: Identity("alice", {"viewer"}, {"*"}, {"sub": "alice"})
    ))
    identity = mcp_auth.resolve_mcp_identity("Bearer signed-token", "app-b")
    assert identity.user_id == "alice"


def test_audit_operator_role_required():
    with pytest.raises(IdentityError, match="OPERATOR_ROLE_REQUIRED"):
        mcp_auth.require_mcp_operator(Identity("alice", {"viewer"}, {"app-a"}, {}))
    mcp_auth.require_mcp_operator(Identity("operator", {"operator"}, {"app-a"}, {}))
    mcp_auth.require_mcp_operator(Identity("admin", {"admin"}, {"*"}, {}))
