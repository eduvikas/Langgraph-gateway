from fastapi import APIRouter, Depends
from app.security.deps import require_operator
from app.config import get_settings
from app.audit.store import build_audit_store
router=APIRouter(tags=["security"], dependencies=[Depends(require_operator)])
@router.get("/security/audit")
def recent_audit(limit:int=50): return {"events":build_audit_store(get_settings()).recent(min(max(limit,1),200))}
