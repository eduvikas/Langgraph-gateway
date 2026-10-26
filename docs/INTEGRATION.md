# Integrating an application over REST

The supported runtime is the FastAPI + LangGraph application in `app/`. It exposes `POST /v1/chat`; the archived OpenAI-compatible HTTP gateway is not the supported integration surface. To reach the gateway from an MCP client instead, see [MCP.md](MCP.md).

## Example request

```http
POST /v1/chat
Content-Type: application/json
Authorization: Bearer <JWT when AUTH_ENABLED=true>
```

```json
{
  "session_id": "claims-run-001",
  "application_id": "demo-app",
  "user_id": "service-user",
  "prompt": "Compare these two architecture options and explain the trade-offs.",
  "routing": {
    "task_type": "reasoning",
    "priority": "quality"
  }
}
```

The `routing` object is optional. Supported `task_type` values are `general`, `reasoning`, `coding`, and `general_fast`; supported priorities are `balanced`, `quality`, `latency`, and `cost`. Optional `required_capabilities` can further constrain eligible profiles. These are routing hints only: the application policy remains authoritative.

## Response fields to demonstrate

- `model` and `provider`: the model that actually answered, including failover outcomes
- `route.reason`: the routing hint/classification rationale
- `governance`: allow/block decision and reason
- `budget`: spend, limit, remaining amount and alert status
- `usage` and `economics`: provider-reported or adapter-provided token counts, cost and baseline comparisons
- `cache_hit` and `evaluation`: cache and response-quality outcomes

## Integration guardrails

- Keep the gateway key/JWT server-side; never put secrets in browser code or source control.
- Enable authentication and configure real identity claims before network exposure.
- Do not treat a routing hint as authorization to access a model or sensitive data.
- Validate actual model identifiers and price tables against the provider account being used.
- Treat heuristic routing and estimated preflight tokens as a starting point; evaluate them against representative workloads.
- Budget admission uses atomic reservations in shared SQL storage (see [HARDENING.md](HARDENING.md)); run it against PostgreSQL and test concurrency in your environment before relying on hard limits.
