from fastapi import APIRouter, Depends
from app.security.deps import require_operator
from app.usage.ledger import ledger
router = APIRouter(tags=["usage"], dependencies=[Depends(require_operator)])
@router.get("/usage/recent")
def recent_usage(limit: int = 20):
    return {"events": ledger.recent(max(1, min(limit, 100)))}
