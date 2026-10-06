from fastapi import APIRouter
from app.api.routes_chat import health
from app.usage.ledger import ledger
from app.evaluation.store import store
from app.control_tower.metrics import ControlTower
router=APIRouter(tags=['control-tower'])
@router.get('/control-tower/overview')
def overview():
    return ControlTower(ledger,store,health).snapshot()
@router.get('/evaluations/recent')
def evaluations(limit:int=20): return {'events':store.recent(max(1,min(limit,100)))}
