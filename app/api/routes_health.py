from fastapi import APIRouter
from sqlalchemy import create_engine, text
from app.config import get_settings
router=APIRouter(tags=["health"])
@router.get("/health")
def health(): return {"status":"ok","version":"3.0.0"}
@router.get("/ready")
def ready():
    s=get_settings(); checks={"openai_api_key_configured":bool(s.openai_api_key),"model_configured":bool(s.openai_model),"database_configured":bool(s.database_url)}
    try:
        engine=create_engine(s.database_url, future=True, pool_pre_ping=True)
        try:
            with engine.connect() as conn: conn.execute(text("SELECT 1"))
            checks["database_reachable"] = True
        finally:
            engine.dispose()
    except Exception:
        checks["database_reachable"] = False
    if s.rate_limiter_backend.lower() == "redis" or (s.cache_enabled and s.cache_backend.lower() == "redis"):
        try:
            import redis
            client=redis.from_url(s.redis_url, socket_connect_timeout=2, socket_timeout=2)
            checks["redis_reachable"] = bool(client.ping())
        except Exception:
            checks["redis_reachable"] = False
    required=["database_reachable"]
    if s.app_env.lower() in {"prod", "production"}:
        required += ["openai_api_key_configured", "model_configured"]
        if s.rate_limiter_backend.lower() == "redis": required.append("redis_reachable")
    is_ready=all(checks.get(k,False) for k in required)
    return {"status":"ready" if is_ready else "not_ready", "checks":checks}
