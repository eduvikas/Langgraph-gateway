from fastapi import APIRouter, Depends
from app.security.deps import require_operator
from app.api.routes_chat import health, budget
from app.usage.ledger import ledger
from app.evaluation.store import store
from app.control_tower.metrics import ControlTower
router=APIRouter(tags=['control-tower'], dependencies=[Depends(require_operator)])
@router.get('/control-tower/overview')
def overview():
    return ControlTower(ledger,store,health,budget).snapshot()
@router.get('/control-tower/economics')
def economics(days:int=1): return ControlTower(ledger,store,health,budget).economics(max(1,min(days,90)))
@router.get('/evaluations/recent')
def evaluations(limit:int=20): return {'events':store.recent(max(1,min(limit,100)))}
