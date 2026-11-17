"""Authentication and application-scope helpers shared by the MCP adapter.

Remote MCP requests must supply a Bearer JWT. For local stdio development only,
operators may explicitly enable an environment-backed developer identity.
"""
from __future__ import annotations

import dataclasses
import os
from app.config import get_settings
from app.security.identity import Identity, IdentityError, IdentityProvider


def resolve_mcp_identity(authorization: str | None, application_id: str | None = None) -> Identity:
    settings = get_settings()
    if authorization and authorization.lower().startswith("bearer "):
        identity = IdentityProvider(settings).authenticate(authorization, "", application_id)
    else:
        allow_local = os.getenv("MCP_ALLOW_INSECURE_LOCAL", "false").lower() == "true"
        if (not allow_local or settings.app_env.lower() in {"prod", "production"}
                or settings.auth_enabled):
            raise IdentityError("MCP_BEARER_TOKEN_REQUIRED")
        dev_user = os.getenv("MCP_DEV_USER_ID", "").strip()
        if not dev_user:
            raise IdentityError("MCP_DEV_USER_ID_REQUIRED_FOR_LOCAL_DEVELOPMENT")
        identity = IdentityProvider(settings).authenticate(None, dev_user, application_id)
        # Least privilege by default: a local dev identity is a plain `developer`. Opt in to control-plane
        # tools explicitly, e.g. MCP_DEV_ROLES=developer,operator. Ignored whenever a Bearer token is used.
        dev_roles = {r.strip() for r in os.getenv("MCP_DEV_ROLES", "developer").split(",") if r.strip()}
        identity = dataclasses.replace(identity, roles=dev_roles or {"developer"})
    if application_id is not None:
        if not identity.applications or (application_id not in identity.applications and "*" not in identity.applications):
            raise IdentityError("APPLICATION_NOT_ASSIGNED")
    return identity


def require_mcp_operator(identity: Identity) -> None:
    if not (identity.roles & {"admin", "operator"}):
        raise IdentityError("OPERATOR_ROLE_REQUIRED")
