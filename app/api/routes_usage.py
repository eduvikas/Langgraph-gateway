from fastapi import APIRouter
from app.usage.ledger import ledger
router = APIRouter(tags=["usage"])
@router.get("/usage/recent")
def recent_usage(limit: int = 20):
    return {"events": ledger.recent(max(1, min(limit, 100)))}
