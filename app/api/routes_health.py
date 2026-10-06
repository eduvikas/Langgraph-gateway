from fastapi import APIRouter
from app.config import get_settings
router=APIRouter(tags=["health"])
@router.get("/health")
def health(): return {"status":"ok","version":"2.2.0"}
@router.get("/ready")
def ready():
    s=get_settings(); configured=bool(s.openai_api_key) and bool(s.openai_model)
    return {"status":"ready" if configured else "not_ready","checks":{"openai_api_key_configured":bool(s.openai_api_key),"model_configured":bool(s.openai_model),"database_configured":bool(s.database_url)}}
