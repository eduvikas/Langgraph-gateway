
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
APP = "demo-app"


def payload(result):
    if result.isError:
        raise RuntimeError(
            "MCP tool error: " +
            " ".join(
                getattr(c, "text", "")
                for c in result.content
            )
        )

    structured = getattr(result, "structuredContent", None)

    if structured:
        return structured.get("result", structured)

    text = "".join(
        getattr(c, "text", "")
        for c in result.content
    )

    return json.loads(text)


async def main():

    env = os.environ.copy()

    env.update({
        "APP_ENV": "local",
        "MCP_TRANSPORT": "stdio",
        "MCP_ALLOW_INSECURE_LOCAL": "true",
        "MCP_DEV_USER_ID": "live-mcp-demo",
        "MCP_DEV_ROLES": "developer,operator",
        "MOCK_PROVIDER_ENABLED": "false",
        "LOG_STREAM": "stderr"
    })

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(ROOT),
        env=env
    )

    print("\nSTARTING LIVE MCP SERVER")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()

            tools = await session.list_tools()

            print("\nDISCOVERED MCP TOOLS")

            for tool in tools.tools:
                print("[PASS]", tool.name)

            assert len(tools.tools) == 6

            health = payload(
                await session.call_tool(
                    "gateway_health", {}
                )
            )

            print("\nGATEWAY HEALTH")
            print(json.dumps(health, indent=2))

            print("\nEXECUTING REAL OPENAI REQUEST")

            response = payload(
                await session.call_tool(
                    "gateway_chat",
                    {
                        "application_id": APP,
                        "task_type": "general_fast",
                        "priority": "cost",
                        "data_classification": "internal",
                        "prompt": (
                            "Reply with the single word: "
                            "MCP_LIVE_SUCCESS"
                        )
                    }
                )
            )

            gov = response.get("governance", {})
            usage = response.get("usage", {})
            economics = response.get("economics", {})

            print("\nLIVE MCP RESPONSE")
            print("Decision:", gov.get("decision"))
            print("Provider:", response.get("provider"))
            print("Model:", response.get("model"))
            print("Request ID:", response.get("request_id"))
            print("Response:", response.get("response"))

            print("\nPROVIDER USAGE")
            print("Input:", usage.get("input_tokens"))
            print("Output:", usage.get("output_tokens"))
            print("Total:", usage.get("total_tokens"))

            print(
                "Gateway cost:",
                economics.get("cost_usd")
            )

            assert gov.get("decision") == "ALLOW"
            assert response.get("provider") == "openai"
            assert response.get("request_id")
            assert usage.get("total_tokens", 0) > 0

            rid = response["request_id"]

            print("\nCHECKING ROUTING AUDIT")

            audit = payload(
                await session.call_tool(
                    "gateway_get_routing_decision",
                    {
                        "request_id": rid,
                        "application_id": APP
                    }
                )
            )

            print(json.dumps(audit, indent=2, default=str))

            assert audit.get("found") is True

            print("\nCHECKING USAGE LEDGER")

            ledger = payload(
                await session.call_tool(
                    "gateway_get_usage",
                    {
                        "application_id": APP,
                        "limit": 10
                    }
                )
            )

            events = ledger.get("events", [])

            matching = [
                e for e in events
                if e.get("request_id") == rid
            ]

            print("Usage events:", len(events))
            print("Matching request events:", len(matching))

            assert matching, "Live request missing from usage ledger"

            print("\n===================================")
            print("LIVE MCP END-TO-END TEST PASSED")
            print("Real OpenAI + MCP + Audit + Usage")
            print("===================================")


if __name__ == "__main__":
    asyncio.run(main())