"""MCP integration adapter for the canonical FastAPI + LangGraph gateway.

Run locally over stdio: python -m app.mcp_server
This adapter intentionally supports stdio only in this release. Do not expose it
as a remote HTTP MCP endpoint until an SDK-supported per-client OAuth/JWT verifier
and TLS deployment have been configured and integration-tested.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4
from typing import Any

# stdout is reserved for MCP JSON-RPC frames. Gateway logs must go to stderr, and this has to be
# set before app.main is imported (it configures logging at import time).
os.environ.setdefault("LOG_STREAM", "stderr")

import httpx
from mcp.server.fastmcp import FastMCP, Context

from app.config import get_settings
from app.mcp_auth import require_mcp_operator, resolve_mcp_identity
from app.main import app as gateway_app
from app.api.routes_chat import audit, budget, ledger
from app.audit.store import AuditEvent
from app.economics.budget import estimate_tokens
from app.usage.ledger import UsageEvent
from sqlalchemy.orm import Session

mcp = FastMCP("enterprise-ai-gateway", instructions=(
    "Tools for governed model execution, cost estimates, application budgets, "
    "routing audit retrieval, usage reporting, and health checks. All calls are "
    "subject to the gateway's identity, policy, budget, and audit controls."
))


def _authorization(ctx: Context | None) -> str | None:
    """Use the inbound remote request's Bearer token; stdio uses an env token."""
    if ctx is not None:
        try:
            request = ctx.request_context.request
            headers = getattr(request, "headers", None)
            if headers is not None:
                # For HTTP transport, never fall back to a server-wide token when
                # a client omitted its own credential.
                return headers.get("authorization")
        except (AttributeError, TypeError):
            pass
    token = (os.getenv("MCP_GATEWAY_BEARER_TOKEN") or "").strip()
    if not token:
        return None
    # Accept the bare JWT (as documented) as well as a full "Bearer <jwt>" value.
    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def _identity(ctx: Context | None, application_id: str | None = None):
    return resolve_mcp_identity(_authorization(ctx), application_id)


def _operator_identity(ctx: Context | None, application_id: str):
    """Control-plane tools (audit, app-wide usage) need an `operator`/`admin` role, as the REST
    control-plane endpoints do, on top of the application-scope check done by `_identity`."""
    identity = _identity(ctx, application_id)
    require_mcp_operator(identity)
    return identity


def _as_dict(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {"detail": "Gateway returned a non-JSON response"}
    if response.status_code >= 400:
        detail = body.get("detail", "Gateway request failed") if isinstance(body, dict) else "Gateway request failed"
        raise RuntimeError(f"Gateway request failed ({response.status_code}): {detail}")
    return body


async def _gateway_request(method: str, path: str, ctx: Context | None, **kwargs) -> dict[str, Any]:
    headers = {}
    auth = _authorization(ctx)
    if auth:
        headers["Authorization"] = auth
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.internal", timeout=65) as client:
        response = await client.request(method, path, headers=headers, **kwargs)
    return _as_dict(response)


@mcp.tool()
async def gateway_chat(
    prompt: str,
    application_id: str,
    task_type: str = "general",
    priority: str = "balanced",
    session_id: str | None = None,
    data_classification: str = "auto",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Execute a prompt through the governed gateway with routing and budget controls.

    `task_type` accepts general, reasoning, coding, or general_fast. `priority`
    accepts balanced, quality, latency, or cost. The caller cannot choose an
    unrestricted provider/model; gateway policies determine eligible models.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    settings = get_settings()
    if len(prompt) > settings.max_prompt_chars:
        raise ValueError(f"prompt exceeds MAX_PROMPT_CHARS ({settings.max_prompt_chars})")
    if task_type not in {"general", "reasoning", "coding", "general_fast"}:
        raise ValueError("unsupported task_type")
    if priority not in {"balanced", "quality", "latency", "cost"}:
        raise ValueError("unsupported priority")
    identity = _identity(ctx, application_id)
    body = {
        "session_id": session_id or f"mcp-{uuid4().hex}",
        "application_id": application_id,
        "user_id": identity.user_id,
        "prompt": prompt,
        "data_classification": data_classification,
        "routing": {"task_type": task_type, "priority": priority},
    }
    return await _gateway_request("POST", "/v1/chat", ctx, json=body)


@mcp.tool()
def gateway_estimate_cost(
    prompt: str,
    application_id: str,
    model: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Estimate input/output cost for an allowlisted model without executing it."""
    _identity(ctx, application_id)
    settings = get_settings()
    model_id = model or settings.openai_model
    if model_id not in settings.allowed_models:
        raise ValueError("model is not in ALLOWED_MODELS")
    if len(prompt) > settings.max_prompt_chars:
        raise ValueError(f"prompt exceeds MAX_PROMPT_CHARS ({settings.max_prompt_chars})")
    provider = "mock" if model_id == "mock-general" else "openai"
    breakdown = budget.estimate_breakdown(provider, model_id, prompt, [])
    estimated_input = estimate_tokens(prompt)
    estimated_output = min(settings.max_output_tokens, settings.budget_output_estimate_tokens)
    return {
        "application_id": application_id,
        "provider": provider,
        "model": model_id,
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "estimated_cost_usd": breakdown.cost_usd if breakdown.priced else None,
        "priced": breakdown.priced,
        "warning": None if breakdown.priced else "No verified price is configured; cost is unknown, not free.",
    }


@mcp.tool()
def gateway_check_budget(application_id: str, ctx: Context | None = None) -> dict[str, Any]:
    """Return budget status for an application the caller is authorized to access."""
    _identity(ctx, application_id)
    return {"application_id": application_id, **budget.status(application_id)}


@mcp.tool()
def gateway_get_routing_decision(
    request_id: str,
    application_id: str,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Fetch one routing audit event. Operator/admin role required; scoped to the caller's application."""
    _operator_identity(ctx, application_id)
    with Session(audit.engine) as db:
        row = db.query(AuditEvent).filter(AuditEvent.request_id == request_id,
                                          AuditEvent.application_id == application_id).order_by(AuditEvent.id.desc()).first()
    if row is None:
        # Same response for absent and out-of-scope IDs avoids cross-tenant enumeration.
        return {"found": False, "request_id": request_id}
    decision = None
    if row.routing_decision:
        try:
            decision = json.loads(row.routing_decision)
        except (TypeError, ValueError):
            decision = {"parse_error": True}
    return {"found": True, "request_id": row.request_id, "event_type": row.event_type,
            "outcome": row.outcome, "classification": row.classification,
            "routing_decision": decision, "created_at": row.created_at.isoformat()}


@mcp.tool()
def gateway_get_usage(
    application_id: str,
    limit: int = 20,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return recent usage rows for an application (maximum 100). Operator/admin role required."""
    _operator_identity(ctx, application_id)
    with Session(ledger.engine) as db:
        rows = (db.query(UsageEvent).filter(UsageEvent.application_id == application_id)
                .order_by(UsageEvent.id.desc()).limit(max(1, min(limit, 100))).all())
    return {"application_id": application_id, "events": [ledger._dict(row) for row in rows]}


@mcp.tool()
async def gateway_health(ctx: Context | None = None) -> dict[str, Any]:
    """Check gateway readiness. Requires an authenticated MCP client."""
    _identity(ctx)
    return await _gateway_request("GET", "/ready", ctx)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport != "stdio":
        raise SystemExit(
            "This release supports MCP_TRANSPORT=stdio only. Do not expose a remote MCP endpoint "
            "until per-client OAuth/JWT verification and TLS have been implemented and tested."
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
