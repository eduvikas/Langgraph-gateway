import time
from uuid import uuid4
from fastapi import Request
from fastapi.responses import JSONResponse
from app.config import validate_production_settings
from fastapi import FastAPI
from app.api.routes_chat import router as chat_router
from app.api.routes_config import router as config_router
from app.api.routes_health import router as health_router
from app.api.routes_sessions import router as sessions_router
from app.api.routes_usage import router as usage_router
from app.api.routes_security import router as security_router
from app.api.routes_control_tower import router as control_tower_router
from app.config import get_settings
from app.observability.logging import configure_logging
settings=get_settings(); configure_logging(settings.log_level)
app=FastAPI(title="Enterprise LangGraph AI Gateway",version="3.0.0",description="Enterprise AI Gateway with identity, RBAC, content security, data classification, audit, durable memory and governance.")
app.include_router(health_router); app.include_router(chat_router,prefix="/v1"); app.include_router(sessions_router,prefix="/v1"); app.include_router(config_router,prefix="/v1"); app.include_router(usage_router,prefix="/v1"); app.include_router(security_router,prefix="/v1"); app.include_router(control_tower_router,prefix="/v1")


@app.on_event("startup")
def enforce_production_configuration():
    validate_production_settings(settings)

@app.middleware("http")
async def request_observability(request: Request, call_next):
    import re
    incoming_id = request.headers.get("x-request-id", "")[:100].strip()
    request_id = incoming_id if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", incoming_id) else f"req_{uuid4().hex}"
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        from app.observability.logging import get_logger
        get_logger("gateway.http").exception("http_request_failed", extra={"request_id": request_id})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/v1/"):
        response.headers["Cache-Control"] = "no-store"
    from app.observability.logging import get_logger
    get_logger("gateway.http").info("http_request_completed", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": elapsed_ms})
    return response
