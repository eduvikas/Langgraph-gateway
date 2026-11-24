
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]

APPLICATION_ID = "demo-app"
EXPECTED_INITIAL_MODEL = "gpt-6-luna"
EXPECTED_FALLBACK_MODEL = "gpt-6.1-terra"

REQUEST_MARKER = f"FAILOVER-TEST-{uuid.uuid4().hex[:12]}"


def print_json(title: str, value) -> None:
    print(f"\n{title}")
    print(json.dumps(value, indent=2, default=str))


def extract_result(result):
    """Convert MCP tool result content into readable Python data."""
    if getattr(result, "isError", False):
        messages = [
            item.text
            for item in getattr(result, "content", [])
            if hasattr(item, "text")
        ]
        raise RuntimeError(
            f"MCP tool returned an error: {'; '.join(messages)}"
        )

    for item in getattr(result, "content", []):
        if not hasattr(item, "text"):
            continue

        raw = item.text

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    return None


async def call_tool(session, name: str, arguments: dict):
    result = await session.call_tool(name, arguments)
    return extract_result(result)


def get_request_id(chat_result: dict) -> str:
    request_id = chat_result.get("request_id")

    if not request_id:
        raise RuntimeError(
            "Chat response did not contain a request_id. "
            "Cannot retrieve the routing audit."
        )

    return request_id


async def main():
    print("=" * 72)
    print("LANGGRAPH GATEWAY - CONTROLLED MCP MODEL FAILOVER TEST")
    print("=" * 72)

    print(f"Project: {ROOT}")
    print(f"Application: {APPLICATION_ID}")
    print(f"Simulated outage: {EXPECTED_INITIAL_MODEL}")
    print(f"Expected fallback: {EXPECTED_FALLBACK_MODEL}")
    print(f"Request marker: {REQUEST_MARKER}")

    env = os.environ.copy()

    env.update(
        {
            "MCP_TRANSPORT": "stdio",
            "MCP_ALLOW_INSECURE_LOCAL": "true",
            "MCP_DEV_USER_ID": "mcp-failover-demo",
            "MCP_DEV_ROLES": "developer,operator",
            "MCP_SIMULATE_MODEL_FAILURE": EXPECTED_INITIAL_MODEL,
            "AUTH_ENABLED": "false",
        }
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["scripts/mcp_failover_server.py"],
        cwd=str(ROOT),
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ---------------------------------------------------------
            # 1. Discover MCP tools
            # ---------------------------------------------------------
            tools_result = await session.list_tools()
            available_tools = [
                tool.name for tool in tools_result.tools
            ]

            print("\nMCP TOOL DISCOVERY")
            for tool_name in available_tools:
                print(f"[PASS] {tool_name}")

            required_tools = {
                "gateway_chat",
                "gateway_get_routing_decision",
                "gateway_get_usage",
                "gateway_check_budget",
            }

            missing = required_tools - set(available_tools)

            if missing:
                raise RuntimeError(
                    f"Required MCP tools missing: {sorted(missing)}"
                )

            # ---------------------------------------------------------
            # 2. Check initial budget
            # ---------------------------------------------------------
            initial_budget = await call_tool(
                session,
                "gateway_check_budget",
                {
                    "application_id": APPLICATION_ID,
                },
            )

            print_json("INITIAL APPLICATION BUDGET", initial_budget)

            # ---------------------------------------------------------
            # 3. Submit the controlled failover workload
            # ---------------------------------------------------------
            print("\nSUBMITTING CONTROLLED FAILOVER WORKLOAD...")
            print("Task: general_fast")
            print("Priority: cost")
            print(f"Expected first model: {EXPECTED_INITIAL_MODEL}")

            chat_result = await call_tool(
                session,
                "gateway_chat",
                {
                    "prompt": (
                        f"{REQUEST_MARKER}: "
                        "Explain in two short sentences why enterprise "
                        "AI gateways need model failover. "
                        "Keep the answer concise."
                    ),
                    "application_id": APPLICATION_ID,
                    "task_type": "general_fast",
                    "priority": "cost",
                    "data_classification": "internal",
                },
            )

            print_json("CHAT RESULT", chat_result)

            if not isinstance(chat_result, dict):
                raise RuntimeError(
                    "Unexpected chat response format."
                )

            request_id = get_request_id(chat_result)

            print(f"\nRequest ID: {request_id}")

            # ---------------------------------------------------------
            # 4. Retrieve routing audit
            # ---------------------------------------------------------
            audit = await call_tool(
                session,
                "gateway_get_routing_decision",
                {
                    "request_id": request_id,
                    "application_id": APPLICATION_ID,
                },
            )

            print_json("ROUTING AUDIT", audit)

            # ---------------------------------------------------------
            # 5. Retrieve usage ledger
            # ---------------------------------------------------------
            usage = await call_tool(
                session,
                "gateway_get_usage",
                {
                    "application_id": APPLICATION_ID,
                    "limit": 20,
                },
            )

            print_json("USAGE LEDGER", usage)

            # ---------------------------------------------------------
            # 6. Retrieve final budget
            # ---------------------------------------------------------
            final_budget = await call_tool(
                session,
                "gateway_check_budget",
                {
                    "application_id": APPLICATION_ID,
                },
            )

            print_json("FINAL APPLICATION BUDGET", final_budget)

            # ---------------------------------------------------------
            # 7. Basic response checks
            # ---------------------------------------------------------
            print("\nFAILOVER VALIDATION")

            actual_model = chat_result.get("model")
            route = chat_result.get("route") or {}

            print(
                f"Final response model: {actual_model}"
            )
            print(
                f"Route failed_over_from: "
                f"{route.get('failed_over_from')}"
            )

            if actual_model == EXPECTED_FALLBACK_MODEL:
                print("[PASS] Response executed on expected fallback model")
            else:
                print(
                    "[FAIL] Unexpected final model. "
                    f"Expected {EXPECTED_FALLBACK_MODEL}, got {actual_model}"
                )

            audit_text = json.dumps(audit, default=str).lower()

            if EXPECTED_INITIAL_MODEL.lower() in audit_text:
                print("[PASS] Initial model appears in routing audit")
            else:
                print(
                    "[WARN] Initial model not found in audit output. "
                    "Inspect the audit fields."
                )

            if EXPECTED_FALLBACK_MODEL.lower() in audit_text:
                print("[PASS] Fallback model appears in routing audit")
            else:
                print(
                    "[WARN] Fallback model not found in audit output."
                )

            if actual_model != EXPECTED_FALLBACK_MODEL:
                raise RuntimeError(
                    "Failover validation failed: expected Terra "
                    "to execute the request."
                )

            print("\n" + "=" * 72)
            print("FAILOVER TEST COMPLETED - CHECK AUDIT AND USAGE DETAILS")
            print("=" * 72)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nFAILOVER TEST FAILED: {exc}")
        sys.exit(1)
