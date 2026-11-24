
import os
import sys
import runpy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Local-only test configuration.
os.environ["MCP_ALLOW_INSECURE_LOCAL"] = "true"
os.environ["MCP_DEV_USER_ID"] = "mcp-failover-demo"
os.environ["MCP_DEV_ROLES"] = "developer,operator"
os.environ["MCP_TRANSPORT"] = "stdio"
os.environ["MCP_SIMULATE_MODEL_FAILURE"] = "gpt-6-luna"

from app.providers.factory import get_provider as real_get_provider
from app.gateway import graph as graph_module

FAIL_MODEL = os.environ["MCP_SIMULATE_MODEL_FAILURE"]


def controlled_get_provider(settings, provider_name="openai"):
    provider = real_get_provider(settings, provider_name)

    if provider_name == "openai":
        original_generate = provider.generate

        def generate(prompt, history, model, max_output_tokens):
            if model == FAIL_MODEL:
                print(
                    f"SIMULATED OUTAGE: {model}",
                    file=sys.stderr,
                    flush=True,
                )
                raise RuntimeError(
                    f"SIMULATED_PROVIDER_OUTAGE: {model}"
                )

            return original_generate(
                prompt=prompt,
                history=history,
                model=model,
                max_output_tokens=max_output_tokens,
            )

        provider.generate = generate

    return provider


graph_module.get_provider = controlled_get_provider

# Fail fast if the intended local identity configuration isn't active.
from app.mcp_auth import resolve_mcp_identity

identity = resolve_mcp_identity(None, "demo-app")
print(
    f"FAILOVER TEST IDENTITY: user={identity.user_id}, "
    f"roles={sorted(identity.roles)}",
    file=sys.stderr,
    flush=True,
)

runpy.run_module("app.mcp_server", run_name="__main__")