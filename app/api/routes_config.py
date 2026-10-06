from fastapi import APIRouter
from app.config import get_settings
router=APIRouter(tags=["configuration"])
@router.get("/config")
def config():
    s=get_settings(); return {"app_name":s.app_name,"environment":s.app_env,"version":"2.3.0","provider":"openai","model":s.openai_model,"memory_backend":s.memory_backend,"rate_limiter_backend":s.rate_limiter_backend,"database_url_configured":bool(s.database_url),"redis_url_configured":bool(s.redis_url),"auth_enabled":s.auth_enabled,"jwt_algorithm":s.jwt_algorithm,"security_controls":{"block_secrets":s.block_secrets,"block_prompt_injection":s.block_prompt_injection},"allowed_applications":sorted(s.allowed_applications),"allowed_models":sorted(s.allowed_models),"max_prompt_chars":s.max_prompt_chars,"max_output_tokens":s.max_output_tokens,"max_requests_per_session":s.max_requests_per_session,"rate_limit_requests":s.rate_limit_requests,"rate_limit_window_seconds":s.rate_limit_window_seconds,"openai_api_key_configured":bool(s.openai_api_key)}
