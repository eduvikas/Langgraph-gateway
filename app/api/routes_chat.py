from uuid import uuid4
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from app.config import get_settings
from app.gateway.graph import build_gateway_graph
from app.gateway.state import GatewayState
from app.governance.engine import get_governance_engine
from app.memory.store import session_store
from app.limits.rate_limiter import build_rate_limiter
from app.usage.ledger import build_ledger
from app.audit.store import build_audit_store
from app.security.identity import IdentityError
router=APIRouter(tags=["chat"]); settings=get_settings(); governance=get_governance_engine(settings); limiter=build_rate_limiter(settings); ledger=build_ledger(settings); audit=build_audit_store(settings); graph,health=build_gateway_graph(settings,session_store,governance,limiter,audit)
class ChatRequest(BaseModel):
    session_id:str=Field(min_length=1,max_length=200); application_id:str=Field(min_length=1,max_length=100); user_id:str=Field(min_length=1,max_length=100); prompt:str=Field(min_length=1); data_classification:str="auto"
@router.post("/chat")
def chat(request:ChatRequest, authorization:str|None=Header(default=None)):
    request_id=f"req_{uuid4().hex}"; state:GatewayState={"request_id":request_id,"session_id":request.session_id,"application_id":request.application_id,"user_id":request.user_id,"prompt":request.prompt,"authorization":authorization}
    try: result=graph.invoke(state)
    except IdentityError as exc: raise HTTPException(status_code=401,detail=str(exc))
    except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc))
    except ValueError as exc: raise HTTPException(status_code=503,detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=502,detail=f"Model execution failed: {exc}")
    usage={"input_tokens":result.get("input_tokens",0),"output_tokens":result.get("output_tokens",0),"total_tokens":result.get("total_tokens",0)}
    ledger.record(request_id=request_id,user_id=result.get("user_id",request.user_id),application_id=request.application_id,session_id=request.session_id,provider=result.get("selected_provider","openai"),model=result.get("selected_model",settings.openai_model),**usage,decision=result.get("decision","UNKNOWN"),status="blocked" if result.get("decision")=="BLOCK" else "success")
    base={"request_id":request_id,"session_id":request.session_id,"application_id":request.application_id,"identity":{"user_id":result.get("user_id"),"roles":sorted(result.get("roles",set())),"authenticated":result.get("authenticated",False)},"security":{"classification":result.get("data_classification"),"findings":result.get("security_findings",[])},"governance":{"decision":result.get("decision"),"reason":result.get("block_reason") or None},"rate_limit":{"remaining":result.get("rate_remaining")}}
    if result.get("decision")=="BLOCK": return base
    base.update({"model":result.get("selected_model"),"provider":result.get("selected_provider"),"route":{"reason":result.get("route_reason"),"score":result.get("route_score")},"response":result.get("response"),"cache_hit":False,"estimated_cost_usd":result.get("estimated_cost_usd",0),"evaluation":result.get("evaluation"),"usage":usage}); return base
