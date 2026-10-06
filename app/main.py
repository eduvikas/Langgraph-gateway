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
app=FastAPI(title="LangGraph Gateway V2.3",version="2.6.0",description="Enterprise AI Gateway with identity, RBAC, content security, data classification, audit, durable memory and governance.")
app.include_router(health_router); app.include_router(chat_router,prefix="/v1"); app.include_router(sessions_router,prefix="/v1"); app.include_router(config_router,prefix="/v1"); app.include_router(usage_router,prefix="/v1"); app.include_router(security_router,prefix="/v1"); app.include_router(control_tower_router,prefix="/v1")
