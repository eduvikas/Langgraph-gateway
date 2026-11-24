import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent
APPLICATION_ID = "demo-app"

WORKLOADS = [
    {
        "name": "A - ECONOMY",
        "task_type": "general_fast",
        "priority": "cost",
        "session_id": "mcp-economy-test",
        "prompt": "Define an API gateway in two sentences and explain its main purpose.",
        "expected_model": "gpt-6-luna",
    },
    {
        "name": "B - BALANCED",
        "task_type": "general",
        "priority": "balanced",
        "session_id": "mcp-balanced-test",
        "prompt": (
            "Explain the architecture of a production enterprise AI gateway. "
            "Cover model routing, governance, observability, budget controls and resilience."
        ),
        "expected_model": "gpt-6.1-terra",
    },
    {
        "name": "C - PREMIUM REASONING",
        "task_type": "reasoning",
        "priority": "quality",
        "session_id": "mcp-reasoning-test",
        "prompt": (
            "Compare three enterprise AI gateway architecture approaches. "
            "Derive a recommendation considering resilience, governance, cost, "
            "scalability and operational complexity. Explain the trade-offs."
        ),
        "expected_model": "gpt-6.1-sol",
    },
]


def unpack(result):
    if result.isError:
        message = " ".join(
            getattr(item, "text", str(item)) for item in result.content
        )
        raise RuntimeError(message)

    structured = getattr(result, "structuredContent", None)
    if structured:
        if isinstance(structured, dict):
            return structured.get("result", structured)
        return structured

    text = "".join(
        getattr(item, "text", "") for item in result.content
    )
    try:
        return json.loads(text)
    except ValueError:
        return {"raw_response": text}


async def main():
    env = os.environ.copy()

    # Local stdio development identity only. Do not expose this configuration remotely.
    env["MCP_TRANSPORT"] = "stdio"
    env["AUTH_ENABLED"] = "false"
    env["MCP_ALLOW_INSECURE_LOCAL"] = "true"
    env["MCP_DEV_USER_ID"] = "mcp-demo-operator"
    env["MCP_DEV_ROLES"] = "developer,operator"

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(ROOT),
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            available = {
                tool.name for tool in (await session.list_tools()).tools
            }
            required = {
                "gateway_chat",
                "gateway_get_routing_decision",
                "gateway_get_usage",
                "gateway_check_budget",
            }

            print("\nMCP TOOL DISCOVERY")
            for name in sorted(required):
                print(f"[{'PASS' if name in available else 'FAIL'}] {name}")

            missing = required - available
            if missing:
                raise RuntimeError(f"Missing MCP tools: {sorted(missing)}")

            print("\nINITIAL APPLICATION BUDGET")
            budget_result = unpack(
                await session.call_tool(
                    "gateway_check_budget",
                    {"application_id": APPLICATION_ID},
                )
            )
            print(json.dumps(budget_result, indent=2))

            for workload in WORKLOADS:
                print("\n" + "=" * 65)
                print(workload["name"])
                print(
                    f"Task: {workload['task_type']} | "
                    f"Priority: {workload['priority']}"
                )
                print(f"Expected model: {workload['expected_model']}")

                chat = unpack(
                    await session.call_tool(
                        "gateway_chat",
                        {
                            "prompt": workload["prompt"],
                            "application_id": APPLICATION_ID,
                            "task_type": workload["task_type"],
                            "priority": workload["priority"],
                            "session_id": workload["session_id"],
                            "data_classification": "internal",
                        },
                    )
                )

                request_id = chat.get("request_id")
                print("\nMCP CHAT RESULT")
                print(json.dumps(chat, indent=2, default=str))

                if not request_id:
                    print("[FAIL] No request_id returned; cannot verify audit.")
                    continue

                audit = unpack(
                    await session.call_tool(
                        "gateway_get_routing_decision",
                        {
                            "request_id": request_id,
                            "application_id": APPLICATION_ID,
                        },
                    )
                )

                decision = audit.get("routing_decision") or {}
                selected = decision.get("selected_model")
                executed = decision.get("final_executed_model")

                print("\nROUTING AUDIT")
                print(json.dumps(audit, indent=2, default=str))

                print("\nWORKLOAD VERIFICATION")
                print(f"Request ID: {request_id}")
                print(f"Expected:   {workload['expected_model']}")
                print(f"Selected:   {selected}")
                print(f"Executed:   {executed}")
                print(f"Audit found: {audit.get('found')}")

                if audit.get("found") and executed:
                    status = (
                        "PASS"
                        if executed == workload["expected_model"]
                        else "CHECK - actual model differs from expectation"
                    )
                    print(status)
                else:
                    print("FAIL - execution/audit not confirmed")

            print("\nFINAL APPLICATION BUDGET")
            final_budget = unpack(
                await session.call_tool(
                    "gateway_check_budget",
                    {"application_id": APPLICATION_ID},
                )
            )
            print(json.dumps(final_budget, indent=2))

            print("\nRECENT USAGE LEDGER")
            usage = unpack(
                await session.call_tool(
                    "gateway_get_usage",
                    {"application_id": APPLICATION_ID, "limit": 10},
                )
            )
            print(json.dumps(usage, indent=2, default=str))

            print("\nTHREE-WORKLOAD MCP TEST FINISHED")


if __name__ == "__main__":
    asyncio.run(main())