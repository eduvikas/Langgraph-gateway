from dataclasses import dataclass
from typing import Any
import jwt

@dataclass(frozen=True)
class Identity:
    user_id: str
    roles: set[str]
    applications: set[str]
    claims: dict[str, Any]
    authenticated: bool = True

class IdentityError(Exception):
    pass

class IdentityProvider:
    def __init__(self, settings):
        self.settings = settings

    def authenticate(self, authorization: str | None, requested_user_id: str, application_id: str) -> Identity:
        if not self.settings.auth_enabled:
            if not requested_user_id:
                raise IdentityError("USER_ID_REQUIRED")
            return Identity(requested_user_id, {"developer"}, {application_id}, {"sub": requested_user_id}, False)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise IdentityError("AUTHENTICATION_REQUIRED")
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = jwt.decode(token, self.settings.jwt_secret, algorithms=[self.settings.jwt_algorithm], audience=self.settings.jwt_audience, issuer=self.settings.jwt_issuer, options={"verify_aud": bool(self.settings.jwt_audience), "verify_iss": bool(self.settings.jwt_issuer)})
        except jwt.PyJWTError as exc:
            raise IdentityError("INVALID_TOKEN") from exc
        user_id = str(claims.get("sub") or "")
        if not user_id:
            raise IdentityError("TOKEN_SUBJECT_REQUIRED")
        roles = self._as_set(claims.get("roles") or claims.get("role") or "viewer")
        applications = self._as_set(claims.get("applications") or claims.get("apps") or "")
        if applications and application_id not in applications and "*" not in applications:
            raise IdentityError("APPLICATION_NOT_ASSIGNED")
        if requested_user_id and requested_user_id != user_id:
            raise IdentityError("USER_ID_MISMATCH")
        return Identity(user_id, roles, applications, claims, True)

    @staticmethod
    def _as_set(value: Any) -> set[str]:
        if isinstance(value, list): return {str(x) for x in value}
        return {x.strip() for x in str(value).split(",") if x.strip()}
