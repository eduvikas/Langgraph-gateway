from dataclasses import dataclass

@dataclass(frozen=True)
class RBACDecision:
    allowed: bool
    reason: str | None = None

class RBAC:
    def authorize(self, roles: set[str], required_roles: set[str], action: str) -> RBACDecision:
        if not required_roles or roles.intersection(required_roles):
            return RBACDecision(True)
        if "admin" in roles:
            return RBACDecision(True)
        return RBACDecision(False, f"RBAC_DENIED:{action}")
