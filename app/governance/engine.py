from dataclasses import dataclass
from app.policy.store import PolicyStore
from app.security.policy import classification_allowed
@dataclass
class GovernanceDecision:
    allowed: bool
    reason: str|None=None
class GovernanceEngine:
    def __init__(self, settings, policy_store): self.settings=settings; self.policy_store=policy_store
    def evaluate(self, application_id, model, prompt, request_count, rate_allowed=True, roles=None, data_classification="internal", security_reason=None):
        roles=roles or set(); policy=self.policy_store.get(application_id)
        if application_id not in self.settings.allowed_applications: return GovernanceDecision(False,"APPLICATION_NOT_ALLOWED")
        if not policy.enabled: return GovernanceDecision(False,"APPLICATION_DISABLED")
        if policy.required_roles and not roles.intersection(policy.required_roles) and "admin" not in roles: return GovernanceDecision(False,"RBAC_DENIED:chat")
        if model not in (policy.allowed_models or self.settings.allowed_models): return GovernanceDecision(False,"MODEL_NOT_ALLOWED")
        if not prompt.strip(): return GovernanceDecision(False,"EMPTY_PROMPT")
        if len(prompt) > (policy.max_prompt_chars or self.settings.max_prompt_chars): return GovernanceDecision(False,"PROMPT_TOO_LARGE")
        if request_count > (policy.max_requests_per_session or self.settings.max_requests_per_session): return GovernanceDecision(False,"SESSION_REQUEST_LIMIT_EXCEEDED")
        if not rate_allowed: return GovernanceDecision(False,"RATE_LIMIT_EXCEEDED")
        if security_reason and security_reason == "SECRET_DETECTED" and (self.settings.block_secrets and not policy.allow_secrets): return GovernanceDecision(False,security_reason)
        if security_reason and security_reason == "PROMPT_INJECTION_DETECTED" and (self.settings.block_prompt_injection and not policy.allow_prompt_injection): return GovernanceDecision(False,security_reason)
        if not classification_allowed(data_classification, policy.max_data_classification): return GovernanceDecision(False,"DATA_CLASSIFICATION_NOT_ALLOWED")
        return GovernanceDecision(True)
def get_governance_engine(settings): return GovernanceEngine(settings,PolicyStore(settings.policy_file,settings))
