from uuid import uuid4
from app.economics.accounting import economics_block, record_usage
from app.economics.budget import BudgetService
from app.economics.cache import build_response_cache
from fastapi import APIRouter, HTTPException, Header, Request as StarletteRequest
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
router=APIRouter(tags=["chat"]); settings=get_settings(); governance=get_governance_engine(settings); limiter=build_rate_limiter(settings); ledger=build_ledger(settings); audit=build_audit_store(settings); budget=BudgetService(settings,governance.policy_store,ledger); graph,health=build_gateway_graph(settings,session_store,governance,limiter,audit,budget=budget,cache=build_response_cache(settings))
class ChatRequest(BaseModel):
    routing:dict = Field(default_factory=dict, description="Optional routing hints: task_type, priority, required_capabilities")
    session_id:str=Field(min_length=1,max_length=200); application_id:str=Field(min_length=1,max_length=100); user_id:str=Field(min_length=1,max_length=100); prompt:str=Field(min_length=1); data_classification:str="auto"
@router.post("/chat")
def chat(request:ChatRequest, http_request:StarletteRequest, authorization:str|None=Header(default=None)):
    request_id=getattr(http_request.state, "request_id", None) or f"req_{uuid4().hex}"; state:GatewayState={"request_id":request_id,"session_id":request.session_id,"application_id":request.application_id,"user_id":request.user_id,"prompt":request.prompt,"authorization":authorization,"routing_metadata":request.routing}
    try: result=graph.invoke(state)
    except IdentityError as exc: raise HTTPException(status_code=401,detail=str(exc))
    except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc))
    except ValueError as exc: raise HTTPException(status_code=503,detail=str(exc))
    except Exception as exc:
        from app.observability.logging import get_logger
        get_logger(__name__).exception("model_execution_failed", extra={"request_id":request_id})
        try:
            ledger.record(request_id=request_id, user_id=request.user_id, application_id=request.application_id,
                          session_id=request.session_id, provider="openai", model=settings.openai_model,
                          input_tokens=0, output_tokens=0, total_tokens=0, decision="ERROR", status="error",
                          error=type(exc).__name__, cost_usd=0.0, baseline_cost_usd=0.0,
                          avoided_cost_usd=0.0, priced=False, cache_hit=False, tokens_avoided=0)
            audit.record(event_type="MODEL_EXECUTION_FAILED", request_id=request_id, user_id=request.user_id,
                         application_id=request.application_id, session_id=request.session_id,
                         outcome="ERROR", classification="unknown", details=type(exc).__name__)
        except Exception:
            get_logger(__name__).exception("failure_audit_write_failed", extra={"request_id":request_id})
        detail = str(exc) if settings.app_env.lower() not in {"prod", "production"} else "Model execution failed"
        raise HTTPException(status_code=502,detail=detail)
    usage=record_usage(ledger,request_id=request_id,request=request,result=result,default_model=settings.openai_model)
    base={"request_id":request_id,"session_id":request.session_id,"application_id":request.application_id,"identity":{"user_id":result.get("user_id"),"roles":sorted(result.get("roles",set())),"authenticated":result.get("authenticated",False)},"security":{"classification":result.get("data_classification"),"findings":result.get("security_findings",[])},"governance":{"decision":result.get("decision"),"reason":result.get("block_reason") or None},"rate_limit":{"remaining":result.get("rate_remaining")},"budget":budget.status(request.application_id)}
    if result.get("decision")=="BLOCK": return base
    base.update({"model":result.get("selected_model"),"provider":result.get("selected_provider"),"route":{"reason":result.get("route_reason"),"score":result.get("route_score"),"failed_over_from":result.get("failed_models",[])},"response":result.get("response"),"cache_hit":bool(result.get("cache_hit")),"estimated_cost_usd":result.get("cost_usd",0),"economics":economics_block(result),"evaluation":result.get("evaluation"),"usage":usage}); return base
