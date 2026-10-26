# Enterprise AI Gateway — Unified Reference Implementation

An AI gateway / LLM FinOps control plane: it centralizes model access, routing, policy, usage measurement, budget enforcement and audit. It has **one canonical runtime**, `app/` (FastAPI + LangGraph), reachable over REST or as a local MCP server. The earlier standalone HTTP gateway is kept under `archive/legacy_http_gateway/` for reference only.

> **Status:** an enterprise-oriented reference implementation, tested end to end against SQLite and a mock provider. It is **not** production-certified. Live provider calls, PostgreSQL/Redis, load and remote MCP are unverified. See [docs/VERIFICATION.md](docs/VERIFICATION.md) for exactly what has and has not been tested.

## What it does

- FastAPI chat API with a LangGraph request workflow
- Identity, application governance, role checks and content-security checks
- Request-aware routing: deterministic classification (or allowlisted client hints) and ranked model profiles
- Provider abstraction (OpenAI and mock), provider health tracking and policy-limited failover
- Atomic budget reservations in shared SQL storage, token/cost accounting, exact-match cache
- Session memory, evaluation, usage ledger, audit events with routing decisions, control-tower endpoints
- MCP server (stdio) exposing six governed tools to any MCP client

## Documentation

| Document | Read it for |
|---|---|
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Calling the gateway over REST |
| [docs/MCP.md](docs/MCP.md) | MCP tools, roles, JWT setup, client config, error codes |
| [docs/SHOWCASE.md](docs/SHOWCASE.md) | The leadership dashboard: real run data, live proof checks, how to regenerate |
| [docs/ENGINEERING.md](docs/ENGINEERING.md) | How routing, failover and budget checks work; validation checklist |
| [docs/HARDENING.md](docs/HARDENING.md) | Production configuration, deployment, security limits |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | The single source of truth for test results and what is unverified |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each version |

## Canonical request flow

```text
HTTP request (or MCP tool call)
  -> identity/authentication
  -> content security + classification
  -> request classifier (or allowlisted client routing hints)
  -> filter models by application policy
  -> rank eligible models ONCE and persist candidate order
  -> governance decision
  -> session history + cache lookup
  -> budget reservation (atomic) + pricing check
  -> execute selected model first; policy-compliant failover only if needed
  -> settle reservation to actual cost; evaluate response
  -> usage, audit, memory and economics reporting
```

The selected model is carried from routing into budget estimation and execution; execution does not re-rank the model list, and failover stays inside the pre-ranked, policy-eligible candidates. The classifier uses transparent heuristics, not semantic understanding; supply optional `routing` hints for controlled tests.

## Repository structure

```text
app/                         # The only supported runtime
  api/                       # FastAPI endpoints
  gateway/                   # LangGraph workflow and state
  routing/                   # Model profiles, health and request classifier
  economics/                 # Pricing, budget reservations, cache and accounting
  providers/                 # Provider abstraction, OpenAI and mock adapters
  security/ governance/      # Identity, RBAC, content security and policy
  usage/ audit/ evaluation/  # Usage ledger, audit and quality evaluation
  mcp_server.py mcp_auth.py  # MCP adapter (stdio)
config/                      # Application policies, MCP client example
docs/                        # Documentation (see table above)
architecture/                # Architecture diagrams and deck
scripts/                     # Demos, MCP smoke test, pricing check
showcase/                    # Leadership dashboard (HTML) and the real run data behind it
demo/                        # Recorded replay of the MCP walkthrough
tests/                       # Unit, API and MCP integration tests
archive/legacy_http_gateway/ # Retired duplicate implementation (reference only)
```

## Run locally (Windows, VS Code, no admin rights, no `uv` required)

Use Python 3.11+ and the VS Code terminal.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

If PowerShell blocks activation, use a Command Prompt terminal and run `.venv\Scripts\activate.bat`.

Open `http://127.0.0.1:8000/docs` for the API documentation. The default development configuration has authentication disabled and uses the mock provider; do not expose it to a network or use it in production. Before production-like testing set a strong `JWT_SECRET`, enable `AUTH_ENABLED=true` and review the application policies in `config/policies.json`.

Example `POST /v1/chat` body:

```json
{
  "session_id": "demo-session-1",
  "application_id": "demo-app",
  "user_id": "demo-user",
  "prompt": "Debug this Python function and explain the stack trace",
  "routing": { "task_type": "coding", "priority": "quality" }
}
```

Task hints: `general`, `reasoning`, `coding`, `general_fast`. Priorities: `balanced`, `quality`, `latency`, `cost`. Hints are routing inputs, not permissions; application policy still decides which models are eligible. More in [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Use it from an MCP client

The stdio server exposes `gateway_chat`, `gateway_estimate_cost`, `gateway_check_budget`, `gateway_health` and two operator-only tools, `gateway_get_routing_decision` and `gateway_get_usage`. The model is chosen by gateway policy, never by the caller.

```powershell
python -m app.mcp_server          # normally launched by the MCP client; see config/mcp-client.example.json
python scripts/mcp_smoke_test.py  # drives the real server with the MCP client SDK
python scripts/demo_mcp_walkthrough.py
```

Setup, JWT claims, roles and error codes: [docs/MCP.md](docs/MCP.md).

## Leadership dashboard

Open `showcase/ai-gateway-showcase.html` in a browser. It is built from the records of a real gateway run (simulated model provider), and it recomputes its own totals in the page as proof. See [docs/SHOWCASE.md](docs/SHOWCASE.md).

## Tests

```powershell
python -m compileall -q app tests scripts
python -m pytest -q
```

Results and the list of unverified areas: [docs/VERIFICATION.md](docs/VERIFICATION.md). Add a test for every routing, budget, security, cache and failover change.

## Important engineering limitations

1. The classifier is heuristic and must be evaluated against a representative enterprise workload.
2. Budget admission is an atomic reservation based on estimated tokens, settled to the provider-reported cost. It prevents concurrent requests from over-committing the same remaining budget, but it is not a guaranteed dollar ceiling if real usage exceeds the estimate. Validate it on PostgreSQL under your own concurrency.
3. Prices must be verified against the provider's current published rates. Unknown prices are never reported as free; budgeted requests for unpriced real models are blocked.
4. Local in-memory components are for demonstration. Production needs reviewed shared storage, distributed rate limits and cache, key management, tracing, deployment hardening and recovery tests ([docs/HARDENING.md](docs/HARDENING.md)).
5. Report cost savings as measured only when they rest on actual provider usage and comparable baseline pricing. Mock or synthetic savings are illustrative.

## Portfolio narrative

Position this as an **Enterprise AI Gateway / LLM FinOps control plane**. Demonstrate it with three controlled prompts (simple, coding, reasoning), show the chosen model and why, then budget blocking, content-security blocking, role-based access to audit data, and the usage ledger (`scripts/demo_mcp_walkthrough.py` does this over MCP). Clearly distinguish implemented behaviour from production requirements.

To validate configured pricing metadata (not to fetch or certify current prices), run `python scripts/verify_provider_pricing.py` after setting `MODEL_PRICING_JSON`, and confirm every rate against the official provider pricing page.
