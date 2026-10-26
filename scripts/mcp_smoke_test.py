"""Live stdio smoke test: launches app.mcp_server as a subprocess and drives it with the MCP client SDK.

    python scripts/mcp_smoke_test.py [--mode local|auth|all] [--db PATH]

local: mock provider + local insecure identity (MCP_DEV_ROLES decides developer vs operator).
auth : AUTH_ENABLED=true with real HS256 JWTs passed via MCP_GATEWAY_BEARER_TOKEN (roles, application
       scope, bad signature, expired, missing token). Uses APP_ENV=local so no Postgres/Redis is needed.
Neither mode may be used in production.
"""
import argparse, asyncio, contextlib, json, os, sys, tempfile, time
from pathlib import Path

import jwt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {"gateway_chat", "gateway_estimate_cost", "gateway_check_budget",
            "gateway_get_routing_decision", "gateway_get_usage", "gateway_health"}
MODELS = "gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna,mock-general"
SECRET = "smoke-test-secret-" + "x" * 32
APP, OTHER_APP = "demo-app", "contract-agent"
results: list[bool] = []


def check(name, ok, detail=""):
    results.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}"[:170] if detail else ""), flush=True)


def payload(res):
    if res.isError:
        return {"_error": " ".join(getattr(c, "text", str(c)) for c in res.content)}
    sc = getattr(res, "structuredContent", None)
    if sc:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    text = "".join(getattr(c, "text", "") for c in res.content)
    try:
        return json.loads(text)
    except ValueError:
        return {"_text": text}


def denied(r, code):
    return "_error" in r and code in r["_error"]


def token(sub, roles, apps, *, secret=SECRET, ttl=600):
    now = int(time.time())
    return jwt.encode({"sub": sub, "roles": roles, "applications": apps, "iat": now, "exp": now + ttl}, secret, algorithm="HS256")


@contextlib.asynccontextmanager
async def session(db, **extra):
    env = {**os.environ, "APP_ENV": "local", "MCP_TRANSPORT": "stdio", "MOCK_PROVIDER_ENABLED": "true",
           "OPENAI_API_KEY": "", "ALLOWED_MODELS": MODELS, "DATABASE_URL": f"sqlite:///{db}", "LOG_LEVEL": "ERROR"}
    for k in ("MCP_GATEWAY_BEARER_TOKEN", "MCP_ALLOW_INSECURE_LOCAL", "MCP_DEV_USER_ID", "MCP_DEV_ROLES"):
        env.pop(k, None)
    env.update(extra)
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        yield s


def local_env(roles, user="smoke-user"):
    return {"AUTH_ENABLED": "false", "MCP_ALLOW_INSECURE_LOCAL": "true", "MCP_DEV_USER_ID": user, "MCP_DEV_ROLES": roles}


def auth_env(tok=None):
    env = {"AUTH_ENABLED": "true", "JWT_SECRET": SECRET}
    if tok is not None:
        env["MCP_GATEWAY_BEARER_TOKEN"] = tok
    return env


async def call(s, name, **args):
    return payload(await s.call_tool(name, args))


async def run_local(db):
    print("\n== local mode: plain developer identity ==")
    async with session(db, **local_env("developer")) as s:
        tools = {t.name for t in (await s.list_tools()).tools}
        check("tool discovery (6 tools)", tools == EXPECTED, str(sorted(tools)))
        r = await call(s, "gateway_health"); check("gateway_health", "_error" not in r)
        r = await call(s, "gateway_estimate_cost", prompt="Summarise this contract", application_id=APP, model="mock-general")
        check("gateway_estimate_cost", r.get("model") == "mock-general" and r.get("priced") is True)
        r = await call(s, "gateway_estimate_cost", prompt="x", application_id=APP, model="not-allowed-model")
        check("estimate rejects non-allowlisted model", "_error" in r)
        r = await call(s, "gateway_check_budget", application_id=APP); check("gateway_check_budget", "limit_usd" in r)
        chat = await call(s, "gateway_chat", prompt="Debug this Python function", application_id=APP, task_type="coding", priority="quality")
        ok = chat.get("governance", {}).get("decision") == "ALLOW" and bool(chat.get("response"))
        check("gateway_chat (governed execution)", ok, f"model={chat.get('model')}")
        rid = chat.get("request_id")
        r = await call(s, "gateway_get_routing_decision", request_id=rid, application_id=APP)
        check("developer DENIED gateway_get_routing_decision", denied(r, "OPERATOR_ROLE_REQUIRED"), r.get("_error", "")[-60:])
        r = await call(s, "gateway_get_usage", application_id=APP)
        check("developer DENIED gateway_get_usage", denied(r, "OPERATOR_ROLE_REQUIRED"), r.get("_error", "")[-60:])
        r = await call(s, "gateway_chat", prompt="hi", application_id="no-such-app")
        check("unknown application blocked by governance", r.get("governance", {}).get("decision") == "BLOCK" and not r.get("response"))
        r = await call(s, "gateway_chat", prompt="hi", application_id=APP, task_type="bogus")
        check("invalid task_type rejected", "_error" in r)

    print("\n== local mode: operator identity ==")
    async with session(db, **local_env("developer,operator", "smoke-ops")) as s:
        r = await call(s, "gateway_get_routing_decision", request_id=rid, application_id=APP)
        check("operator reads routing decision", r.get("found") is True, f"outcome={r.get('outcome')}")
        r = await call(s, "gateway_get_routing_decision", request_id=rid, application_id=OTHER_APP)
        check("routing lookup stays application-scoped (other app => found:false)", r.get("found") is False)
        r = await call(s, "gateway_get_usage", application_id=APP, limit=5)
        check("operator reads usage", len(r.get("events", [])) >= 1, f"{len(r.get('events', []))} event(s)")


async def run_auth(db):
    print("\n== auth mode: real JWTs over stdio ==")
    alice = token("alice", ["developer"], [APP])
    async with session(db, **auth_env(alice)) as s:   # bare JWT, as documented
        chat = await call(s, "gateway_chat", prompt="Summarise clause 4", application_id=APP)
        ident = chat.get("identity", {})
        check("bare JWT accepted; identity comes from the token", ident.get("user_id") == "alice" and ident.get("authenticated") is True, json.dumps(ident))
        rid = chat.get("request_id")
        check("developer chat allowed", chat.get("governance", {}).get("decision") == "ALLOW")
        r = await call(s, "gateway_check_budget", application_id=APP); check("developer can check budget", "limit_usd" in r)
        r = await call(s, "gateway_get_routing_decision", request_id=rid, application_id=APP)
        check("developer DENIED routing decision (even for own request)", denied(r, "OPERATOR_ROLE_REQUIRED"))
        r = await call(s, "gateway_get_usage", application_id=APP)
        check("developer DENIED usage", denied(r, "OPERATOR_ROLE_REQUIRED"))
        r = await call(s, "gateway_chat", prompt="hi", application_id=OTHER_APP)
        check("token not assigned to application is refused", denied(r, "APPLICATION_NOT_ASSIGNED"))

    ops = token("ops", ["operator"], [APP])
    async with session(db, **auth_env("Bearer " + ops)) as s:   # full 'Bearer ...' form also accepted
        r = await call(s, "gateway_get_routing_decision", request_id=rid, application_id=APP)
        check("operator reads another user's routing decision", r.get("found") is True and bool(r.get("routing_decision")))
        r = await call(s, "gateway_get_usage", application_id=APP)
        users = {e.get("user_id") for e in r.get("events", [])}
        check("operator usage includes alice's request", "alice" in users, str(sorted(u for u in users if u)))
        r = await call(s, "gateway_get_usage", application_id=OTHER_APP)
        check("operator limited to assigned applications", denied(r, "APPLICATION_NOT_ASSIGNED"))
        chat = await call(s, "gateway_chat", prompt="hello", application_id=APP)
        check("user_id cannot be spoofed: chat runs as the token subject", chat.get("identity", {}).get("user_id") == "ops")

    async with session(db, **auth_env(token("root", ["admin"], ["*"]))) as s:
        r = await call(s, "gateway_get_usage", application_id=OTHER_APP)
        check("admin with wildcard scope reads any application", "_error" not in r and "events" in r)

    for label, env, code in (
        ("forged token (wrong signature) rejected", auth_env(token("mallory", ["admin"], ["*"], secret="not-the-secret-" + "y" * 32)), "INVALID_TOKEN"),
        ("expired token rejected", auth_env(token("alice", ["developer"], [APP], ttl=-60)), "INVALID_TOKEN"),
        ("missing token rejected", auth_env(None), "MCP_BEARER_TOKEN_REQUIRED"),
    ):
        async with session(db, **env) as s:
            r = await call(s, "gateway_check_budget", application_id=APP)
            check(label, denied(r, code), r.get("_error", "")[-60:])


async def main(mode, db):
    if mode in ("local", "all"):
        await run_local(db)
    if mode in ("auth", "all"):
        await run_auth(db)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("local", "auth", "all"), default="all")
    ap.add_argument("--db", default=str(Path(tempfile.mkdtemp()) / "smoke.db"))
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.mode, a.db)))
