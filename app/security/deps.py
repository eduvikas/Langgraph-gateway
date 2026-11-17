"""FastAPI dependency protecting the control-plane endpoints (audit log, usage,
control tower, evaluations, config). These expose per-user activity and
configuration, so with AUTH_ENABLED=true they need a valid token whose roles
include `operator` (`admin` always passes, per RBAC).

With AUTH_ENABLED=false it lets requests through: the same local-development
trust model /v1/chat already uses in that mode. Do not run that mode in production.
"""
from fastapi import Header, HTTPException

from app.config import get_settings
from app.security.identity import IdentityError, IdentityProvider
from app.security.rbac import RBAC

CONTROL_PLANE_ROLES = {"operator"}


def require_operator(authorization: str | None = Header(default=None)):
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    try:
        # application_id=None: control-plane access is not scoped to one application.
        identity = IdentityProvider(settings).authenticate(authorization, "", None)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    decision = RBAC().authorize(identity.roles, CONTROL_PLANE_ROLES, "control_plane")
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return identity
