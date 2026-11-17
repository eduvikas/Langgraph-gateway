# MCP integration

`app/mcp_server.py` exposes the canonical gateway (`app/`) as a [Model Context Protocol](https://modelcontextprotocol.io) server. It is a thin adapter: it forwards to the same FastAPI + LangGraph application in-process (ASGI transport) and does **not** re-implement routing, policy, budget, provider or audit logic.

**Transport:** local **stdio only**. `MCP_TRANSPORT=streamable-http` is refused on purpose. Remote MCP needs per-client OAuth/JWT verification, TLS, rate limits and remote integration tests first. Do not wrap the stdio server in a network proxy.

## Tools and who may call them

| Tool | Purpose | Access |
|---|---|---|
| `gateway_chat` | Run a prompt through the governed `/v1/chat` workflow. The gateway, not the caller, picks the model. | Any identity assigned to the application |
| `gateway_estimate_cost` | Estimate cost for an allowlisted model without calling it. Unknown price returns `priced=false`, never "free". | Any identity assigned to the application |
| `gateway_check_budget` | Budget status for an application. | Any identity assigned to the application |
| `gateway_health` | Gateway readiness. | Any authenticated identity |
| `gateway_get_routing_decision` | One routing audit record. | **`operator` or `admin`** |
| `gateway_get_usage` | Recent usage ledger rows (all users of the application). | **`operator` or `admin`** |

The two operator tools expose per-user activity, so they follow the same rule as the REST control-plane endpoints (`/v1/security/audit`, `/v1/usage/recent`, `/v1/control-tower/*`). Every application-scoped tool also checks that the caller's token is assigned to the application. Operator rights do not widen application scope: an operator token with `applications: ["demo-app"]` cannot read another application. Audit lookups return `found: false` for absent and out-of-scope request IDs alike, so IDs cannot be enumerated across tenants.

## Local setup (Windows / VS Code, no admin rights, no `uv`)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

For local development only, in `.env`:

```dotenv
APP_ENV=local
AUTH_ENABLED=false
MCP_TRANSPORT=stdio
MCP_ALLOW_INSECURE_LOCAL=true
MCP_DEV_USER_ID=local-dev
MCP_DEV_ROLES=developer          # add ",operator" to use the two operator tools
MOCK_PROVIDER_ENABLED=true
```

`MCP_DEV_ROLES` defaults to `developer` (least privilege). It applies only to the local insecure identity and is ignored whenever a Bearer token is supplied. Local insecure mode is rejected when `APP_ENV=production` or `AUTH_ENABLED=true`.

Point an MCP client at the server using [`config/mcp-client.example.json`](../config/mcp-client.example.json) (adjust the paths), restart the client, and call `gateway_health` first, then `gateway_estimate_cost`, `gateway_check_budget` and `gateway_chat`. Start in mock-provider mode.

## Authenticated use (JWT)

Set `AUTH_ENABLED=true` and configure `JWT_SECRET`, `JWT_ISSUER` and `JWT_AUDIENCE` to match your identity provider. Supply a short-lived token to the server process as `MCP_GATEWAY_BEARER_TOKEN`; the bare JWT and a full `Bearer <jwt>` value are both accepted. Pass it through your client's secret mechanism and never commit it.

| Claim | Meaning |
|---|---|
| `sub` | User identity. `gateway_chat` always runs as this user; callers cannot supply a user ID. |
| `roles` (or `role`) | `operator` / `admin` unlock the control-plane tools. Anything else, or no claim, is a plain user. |
| `applications` (or `apps`) | Applications the token may use. `"*"` means all. |

A stdio server process holds one token, so use separate server entries (or processes) for different identities.

### Errors you will see

| Message | Cause |
|---|---|
| `MCP_BEARER_TOKEN_REQUIRED` | No token, and local insecure mode is not enabled |
| `INVALID_TOKEN` | Bad signature, expired, wrong issuer/audience |
| `APPLICATION_NOT_ASSIGNED` | Token is not assigned to the requested application |
| `OPERATOR_ROLE_REQUIRED` | Tool needs `operator`/`admin` |
| `MCP_DEV_USER_ID_REQUIRED_FOR_LOCAL_DEVELOPMENT` | Local insecure mode without `MCP_DEV_USER_ID` |

## Tool contracts

### `gateway_chat`
Required: `prompt`, `application_id`. Optional: `task_type` (`general`, `reasoning`, `coding`, `general_fast`; default `general`), `priority` (`balanced`, `quality`, `latency`, `cost`; default `balanced`), `session_id`, `data_classification` (default `auto`). Returns the normal gateway chat response (`governance`, `route`, `budget`, `usage`, `economics`, ...). A governance block (policy, budget, unsafe content) is a normal response with `governance.decision = "BLOCK"` and no `response`, not a protocol error. Routing hints are inputs, not permissions; application policy still decides which models are eligible.

### `gateway_estimate_cost`
Required: `prompt`, `application_id`. Optional: `model` (must be in `ALLOWED_MODELS`). Returns provider/model, estimated input/output tokens, a nullable estimated USD cost and `priced`.

### `gateway_check_budget`
Required: `application_id`. Returns `limit_usd`, `spent_today_usd`, `reserved_usd`, `remaining_usd`, `utilization`, `alert`, `unlimited`.

### `gateway_get_routing_decision` (operator)
Required: `request_id`, `application_id`. Returns the stored routing decision (task type, priority, candidates, reason, estimated cost, reservation ID, executed model, failover history, cache status), or `found: false`.

### `gateway_get_usage` (operator)
Required: `application_id`. Optional: `limit` (clamped to 1-100). Returns recent usage events for that application only.

### `gateway_health`
No arguments. Returns the readiness payload.

## Operating notes

- **stdout belongs to the protocol.** The server sets `LOG_STREAM=stderr` before importing the gateway so JSON logs never corrupt the JSON-RPC stream. Do not add `print()` calls to server code paths.
- Grant the adapter no broader database or provider credentials than the gateway runtime already has.
- Report skipped or unavailable dependencies instead of treating `compileall` as verification.

## Testing

```powershell
python scripts/mcp_smoke_test.py               # live: real stdio server driven by the MCP client SDK
python scripts/mcp_smoke_test.py --mode auth   # only the JWT scenarios (roles, scope, forged/expired/missing token)
python -m pytest tests/test_mcp_auth.py tests/test_mcp_operator.py tests/test_mcp_contract.py -q
```

The smoke test needs no API key and no network. Current results are recorded in [VERIFICATION.md](VERIFICATION.md).
