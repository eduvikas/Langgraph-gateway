from fastapi import APIRouter
from app.config import get_settings
from app.audit.store import build_audit_store
router=APIRouter(tags=["security"])
@router.get("/security/audit")
def recent_audit(limit:int=50): return {"events":build_audit_store(get_settings()).recent(min(max(limit,1),200))}
