"""Model profiles (what the router can serve) and their consistency with application policies (what is permitted).

The router and the governance layer answer different questions, and each has its own list of model IDs:

* `ModelProfile` list  -> models the router can actually rank and call.
* `AppPolicy.allowed_models` / `Settings.allowed_models` -> models an application is *permitted* to use.

A request is only servable when a model is in both lists. If they drift apart nothing fails loudly: a model that is
permitted but has no profile is simply never chosen, and an application whose permitted models are all unroutable gets
`NO_ELIGIBLE_MODEL` on every request. `validate_model_configuration` makes that drift visible.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.economics.pricing import PRICING
from app.observability.logging import get_logger
from app.routing.classifier import VALID_CAPABILITIES
from app.routing.router import ModelProfile

logger = get_logger(__name__)

MOCK_PROVIDER = "mock"
MOCK_MODEL = "mock-general"

# Built-in fixture profiles used when an API key is set but MODEL_PROFILES_JSON is not. Production must supply its own
# profiles (see validate_production_settings), so these are demo defaults, not a statement about real models.
DEFAULT_OPENAI_PROFILES = (
    {"provider": "openai", "model": "gpt-5.6-sol", "quality": 0.95, "latency": 0.70, "capabilities": ["general", "reasoning", "coding"]},
    {"provider": "openai", "model": "gpt-5.6-terra", "quality": 0.92, "latency": 0.82, "capabilities": ["general", "reasoning", "coding"]},
    {"provider": "openai", "model": "gpt-5.6-luna", "quality": 0.82, "latency": 0.96, "capabilities": ["general", "general_fast"]},
)


class ModelConfigError(ValueError):
    """The model configuration is malformed or internally inconsistent."""


def _profile_from_item(item, index: int) -> ModelProfile:
    if not isinstance(item, dict) or not item.get("provider") or not item.get("model"):
        raise ModelConfigError(f"MODEL_PROFILES_JSON entry {index} must be an object with provider and model")
    capabilities = item.get("capabilities", ["general"])
    if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
        raise ModelConfigError(f"MODEL_PROFILES_JSON entry {index} ({item['model']}) capabilities must be a list of strings")
    in_price, out_price = PRICING.get(item["model"], (0.0, 0.0))
    try:
        quality, latency = float(item.get("quality", 0.8)), float(item.get("latency", 0.8))
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"MODEL_PROFILES_JSON entry {index} ({item['model']}) quality/latency must be numbers") from exc
    return ModelProfile(item["provider"], item["model"], float(in_price), float(out_price), quality, latency,
                        set(capabilities), bool(item.get("enabled", True)))


def build_model_profiles(settings) -> list[ModelProfile]:
    """The profiles the router is built from, for these settings.

    Precedence is unchanged: explicit MODEL_PROFILES_JSON, else the built-in OpenAI fixtures when an API key is set,
    else nothing. The mock profile is appended when the mock provider is enabled and no mock profile was configured."""
    if settings.model_profiles_json:
        try:
            items = json.loads(settings.model_profiles_json)
        except ValueError as exc:
            raise ModelConfigError(f"MODEL_PROFILES_JSON is not valid JSON: {exc}") from exc
        if not isinstance(items, list):
            raise ModelConfigError("MODEL_PROFILES_JSON must be a JSON list of profile objects")
        profiles = [_profile_from_item(item, i) for i, item in enumerate(items)]
    elif settings.openai_api_key:
        profiles = [_profile_from_item(item, i) for i, item in enumerate(DEFAULT_OPENAI_PROFILES)]
    else:
        profiles = []
    if settings.mock_provider_enabled and not any(p.provider == MOCK_PROVIDER for p in profiles):
        profiles.append(ModelProfile(MOCK_PROVIDER, MOCK_MODEL, 0, 0, .40, 1.0, {"general", "general_fast"}))
    return profiles


@dataclass
class ModelConfigReport:
    errors: list[str] = field(default_factory=list)      # an application can never be served, or the config is broken
    warnings: list[str] = field(default_factory=list)    # drift that narrows routing but does not stop service

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ModelConfigError("Inconsistent model configuration: " + "; ".join(self.errors))


def _policy_applications(settings, policy_store) -> dict[str, set[str]]:
    """application -> models it is permitted to use, applying the same fallback governance applies at request time."""
    global_allowed = set(settings.allowed_models)
    result: dict[str, set[str]] = {}
    for app_id in sorted(settings.allowed_applications):
        policy = policy_store.get(app_id) if policy_store is not None else None
        if policy is not None and not policy.enabled:
            continue                                   # a disabled application is never served, so nothing to reconcile
        result[app_id] = set(policy.allowed_models) if policy is not None and policy.allowed_models else set(global_allowed)
    # Policies for applications outside ALLOWED_APPLICATIONS are unreachable (governance blocks them first), so ignore them.
    return result


def validate_model_configuration(settings, profiles, policy_store=None) -> ModelConfigReport:
    """Check that the router's profiles and the permitted-model lists describe the same set of models."""
    report = ModelConfigReport()
    seen: set[tuple[str, str]] = set()
    for p in profiles:
        key = (p.provider, p.model)
        if key in seen:
            report.errors.append(f"duplicate model profile {p.provider}:{p.model}")
        seen.add(key)
        unknown = sorted(set(p.capabilities) - VALID_CAPABILITIES)
        if unknown:
            report.warnings.append(f"profile {p.model} advertises unrecognised capabilities {unknown}; clients cannot require them")
        if p.enabled and p.provider != MOCK_PROVIDER and p.model not in PRICING:
            report.warnings.append(f"profile {p.model} has no price entry; budgeted applications will block it as UNPRICED_MODEL")

    routable = {p.model for p in profiles if p.enabled}
    permitted_anywhere: set[str] = set()
    for app_id, allowed in _policy_applications(settings, policy_store).items():
        permitted_anywhere |= allowed
        unavailable = sorted(allowed - routable)
        if allowed and not (allowed & routable):
            report.errors.append(f"application '{app_id}' permits {sorted(allowed)} but the router can serve none of them, "
                                 f"so every request will be blocked with NO_ELIGIBLE_MODEL")
        elif unavailable:
            report.warnings.append(f"application '{app_id}' permits models the router cannot serve: {unavailable}")
        if not allowed:
            report.errors.append(f"application '{app_id}' has no permitted models")

    for p in profiles:
        if p.enabled and p.model not in permitted_anywhere:
            report.warnings.append(f"profile {p.model} is enabled but no application is permitted to use it")
    return report


def check_model_configuration(settings, profiles, policy_store=None, *, strict: bool | None = None) -> ModelConfigReport:
    """Validate, log what was found, and raise on errors when `strict` (default: only in production)."""
    report = validate_model_configuration(settings, profiles, policy_store)
    for message in report.warnings:
        logger.warning("model_config_warning: %s", message, extra={"detail": message})
    for message in report.errors:
        logger.error("model_config_error: %s", message, extra={"detail": message})
    if strict is None:
        strict = settings.app_env.lower() in {"prod", "production"}
    if strict:
        report.raise_for_errors()
    return report
