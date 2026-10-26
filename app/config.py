from functools import lru_cache
import os
import math
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()
class Settings(BaseModel):
    app_name:str=os.getenv('APP_NAME','langgraph-gateway-v2.6')
    app_env:str=os.getenv('APP_ENV','local'); log_level:str=os.getenv('LOG_LEVEL','INFO')
    openai_api_key:str=os.getenv('OPENAI_API_KEY',''); openai_model:str=os.getenv('OPENAI_MODEL','gpt-5.6-sol')
    max_prompt_chars:int=int(os.getenv('MAX_PROMPT_CHARS','20000')); max_output_tokens:int=int(os.getenv('MAX_OUTPUT_TOKENS','2000'))
    max_requests_per_session:int=int(os.getenv('MAX_REQUESTS_PER_SESSION','50'))
    rate_limit_requests:int=int(os.getenv('RATE_LIMIT_REQUESTS','60')); rate_limit_window_seconds:int=int(os.getenv('RATE_LIMIT_WINDOW_SECONDS','60'))
    database_url:str=os.getenv('DATABASE_URL','sqlite:///./gateway.db'); memory_backend:str=os.getenv('MEMORY_BACKEND','sql')
    rate_limiter_backend:str=os.getenv('RATE_LIMITER_BACKEND','memory'); redis_url:str=os.getenv('REDIS_URL','redis://localhost:6379/0')
    policy_file:str=os.getenv('POLICY_FILE','config/policies.json'); auth_enabled:bool=os.getenv('AUTH_ENABLED','false').lower()=='true'
    jwt_secret:str=os.getenv('JWT_SECRET','change-me-in-production'); jwt_algorithm:str=os.getenv('JWT_ALGORITHM','HS256'); jwt_issuer:str=os.getenv('JWT_ISSUER',''); jwt_audience:str=os.getenv('JWT_AUDIENCE','')
    allow_insecure_local_auth:bool=os.getenv('ALLOW_INSECURE_LOCAL_AUTH','true').lower()=='true'; block_secrets:bool=os.getenv('BLOCK_SECRETS','true').lower()=='true'; block_prompt_injection:bool=os.getenv('BLOCK_PROMPT_INJECTION','true').lower()=='true'; injection_strict:bool=os.getenv('INJECTION_STRICT','false').lower()=='true'
    routing_priority:str=os.getenv('ROUTING_PRIORITY','balanced'); routing_task:str=os.getenv('ROUTING_TASK','general'); mock_provider_enabled:bool=os.getenv('MOCK_PROVIDER_ENABLED','true').lower()=='true'
    circuit_failure_threshold:int=int(os.getenv('CIRCUIT_FAILURE_THRESHOLD','3')); circuit_recovery_seconds:int=int(os.getenv('CIRCUIT_RECOVERY_SECONDS','30'))
    evaluation_enabled:bool=os.getenv('EVALUATION_ENABLED','true').lower()=='true'; evaluation_min_score:float=float(os.getenv('EVALUATION_MIN_SCORE','0.65'))
    default_daily_budget_usd:float=float(os.getenv('DEFAULT_DAILY_BUDGET_USD','0')); budget_output_estimate_tokens:int=int(os.getenv('BUDGET_OUTPUT_ESTIMATE_TOKENS','500')); budget_alert_threshold:float=float(os.getenv('BUDGET_ALERT_THRESHOLD','0.8'))
    cache_enabled:bool=os.getenv('CACHE_ENABLED','true').lower()=='true'; cache_backend:str=os.getenv('CACHE_BACKEND','memory'); cache_ttl_seconds:int=int(os.getenv('CACHE_TTL_SECONDS','3600')); cache_max_entries:int=int(os.getenv('CACHE_MAX_ENTRIES','1000'))
    baseline_model:str=os.getenv('BASELINE_MODEL','gpt-5.6-sol'); mock_pricing_model:str=os.getenv('MOCK_PRICING_MODEL','')
    allowed_applications_raw:str=os.getenv('ALLOWED_APPLICATIONS','demo-app,contract-agent,sre-agent'); allowed_models_raw:str=os.getenv('ALLOWED_MODELS','gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna')
    model_pricing_json:str=os.getenv('MODEL_PRICING_JSON','')
    model_profiles_json:str=os.getenv('MODEL_PROFILES_JSON','')
    request_timeout_seconds:float=float(os.getenv('REQUEST_TIMEOUT_SECONDS','60'))
    pricing_max_age_days:int=int(os.getenv('PRICING_MAX_AGE_DAYS','30'))
    @property
    def allowed_applications(self): return {x.strip() for x in self.allowed_applications_raw.split(',') if x.strip()}
    @property
    def allowed_models(self): return {x.strip() for x in self.allowed_models_raw.split(',') if x.strip()}
@lru_cache
def get_settings(): return Settings()


def validate_production_settings(settings=None):
    """Fail closed on known-dangerous production defaults; does not validate cloud IAM itself."""
    import json
    s = settings or get_settings()
    if s.app_env.lower() not in {"prod", "production"}:
        return True
    problems = []
    if not s.auth_enabled: problems.append("AUTH_ENABLED must be true")
    def is_placeholder(value):
        lowered = str(value or "").strip().lower()
        return (not lowered) or any(marker in lowered for marker in ("replace_with", "replace-me", "placeholder", "change-me", "changeme", "your-secret", "example.com", ".example", "your-identity-provider"))
    if is_placeholder(s.openai_api_key): problems.append("OPENAI_API_KEY must be supplied by the secret manager and cannot be a placeholder")
    if is_placeholder(s.openai_model): problems.append("OPENAI_MODEL must be a real provider-supported model ID")
    if s.jwt_algorithm != "HS256": problems.append("JWT_ALGORITHM must be HS256; asymmetric JWT verification is not configured")
    if len(s.jwt_secret) < 32 or is_placeholder(s.jwt_secret): problems.append("JWT_SECRET must be a non-default secret of at least 32 characters")
    if is_placeholder(s.jwt_issuer): problems.append("JWT_ISSUER must be a real identity-provider issuer URL")
    if is_placeholder(s.jwt_audience): problems.append("JWT_AUDIENCE must be configured and cannot be a placeholder")
    if s.mock_provider_enabled: problems.append("MOCK_PROVIDER_ENABLED must be false")
    if not s.database_url.startswith(("postgresql://", "postgresql+psycopg://")): problems.append("DATABASE_URL must use PostgreSQL in production")
    if s.rate_limiter_backend.lower() != "redis": problems.append("RATE_LIMITER_BACKEND must be redis for shared worker limits")
    if s.cache_enabled and s.cache_backend.lower() != "redis": problems.append("CACHE_BACKEND must be redis when shared production caching is enabled")
    if s.memory_backend.lower() != "sql": problems.append("MEMORY_BACKEND must be sql for shared durable sessions")
    try:
        prices = json.loads(s.model_pricing_json or "{}")
        missing = sorted(m for m in s.allowed_models if m != "mock-general" and m not in prices)
        if missing: problems.append("MODEL_PRICING_JSON missing allowed model prices: " + ", ".join(missing))
        if s.baseline_model not in prices: problems.append("BASELINE_MODEL must have an entry in MODEL_PRICING_JSON")
        for model, p in prices.items():
            if not isinstance(p, dict) or not isinstance(p.get("source"), str) or not p.get("source") or not p.get("verified_on"):
                problems.append(f"MODEL_PRICING_JSON entry {model} must include source and verified_on")
                continue
            if not p["source"].startswith("https://") or is_placeholder(p["source"]):
                problems.append(f"MODEL_PRICING_JSON entry {model} source must be a real HTTPS pricing reference")
            try:
                from datetime import date
                verified = date.fromisoformat(str(p["verified_on"]))
                if verified > date.today(): problems.append(f"MODEL_PRICING_JSON entry {model} verified_on cannot be in the future")
                if (date.today() - verified).days > s.pricing_max_age_days:
                    problems.append(f"MODEL_PRICING_JSON entry {model} is stale; refresh official pricing within {s.pricing_max_age_days} days")
            except ValueError:
                problems.append(f"MODEL_PRICING_JSON entry {model} verified_on must be YYYY-MM-DD")
            try:
                input_rate = float(p.get("input_per_1m", -1))
                output_rate = float(p.get("output_per_1m", -1))
                rates_valid = math.isfinite(input_rate) and math.isfinite(output_rate) and input_rate >= 0 and output_rate >= 0
            except (TypeError, ValueError):
                rates_valid = False
                input_rate = output_rate = -1.0
            if not rates_valid:
                problems.append(f"MODEL_PRICING_JSON entry {model} has invalid or non-finite token prices")
            if model != "mock-general" and input_rate == 0 and output_rate == 0:
                problems.append(f"MODEL_PRICING_JSON entry {model} cannot have zero input and output prices in production")
    except (ValueError, TypeError):
        problems.append("MODEL_PRICING_JSON must be valid JSON")
    try:
        profiles = json.loads(s.model_profiles_json or "[]")
        if not profiles: problems.append("MODEL_PROFILES_JSON must define provider-backed model profiles")
        profile_models = set()
        for profile in profiles:
            if not isinstance(profile, dict) or not profile.get("provider") or not profile.get("model"):
                problems.append("MODEL_PROFILES_JSON entries need provider and model")
                continue
            profile_models.add(profile["model"])
            if profile.get("provider") not in {"openai", "mock"}:
                problems.append(f"MODEL_PROFILES_JSON provider {profile.get('provider')} is not implemented")
            if profile.get("provider") == "mock":
                problems.append("MODEL_PROFILES_JSON must not include mock profiles in production")
            if profile.get("provider") != "mock" and profile["model"] not in prices:
                problems.append(f"MODEL_PROFILES_JSON model {profile['model']} has no verified price entry")
        if profile_models and not s.allowed_models.issubset(profile_models):
            problems.append("ALLOWED_MODELS contains models absent from MODEL_PROFILES_JSON")
    except (ValueError, TypeError):
        problems.append("MODEL_PROFILES_JSON must be valid JSON")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
    return True
