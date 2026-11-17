"""
Drop-in helper for pointing an application's LangChain / LangGraph agents at
the ai-gateway service. Copy this one file into the application.

What it does, and nothing more:
  1. builds a ChatOpenAI client aimed at the gateway (base_url + api_key),
  2. tags every call with app / agent / run / step (and sensitivity if asked),
  3. turns the gateway's two permanent rejections into clear exceptions,
  4. hands back the routing decision (tier, cost, overrides) for logging.

Configuration comes from the environment:
    AI_GATEWAY_URL      e.g. https://ai-gateway.internal/v1
    AI_GATEWAY_KEY      this application's virtual key
    AI_GATEWAY_APP_ID   this application's name (drives its daily budget)
"""
import os
import uuid

import openai
from langchain_openai import ChatOpenAI

GATEWAY_URL = os.getenv("AI_GATEWAY_URL", "http://localhost:8000/v1")
GATEWAY_KEY = os.getenv("AI_GATEWAY_KEY", "dev-key")
APP_ID = os.getenv("AI_GATEWAY_APP_ID", "claims")


class GatewayBlocked(Exception):
    """429: the app's daily budget or this run's budget/step cap is spent.
    Permanent for this run. Stop or degrade; do not retry."""


class PolicyBlocked(Exception):
    """403: the request's own constraints conflict with policy, for example
    sensitive data combined with a minimum tier above small."""


def new_run_id(prefix: str = "run") -> str:
    """One id per agent run. Reuse it on every step so the run budget works."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def make_llm(
    agent: str,
    run_id: str,
    step: int = 0,
    *,
    sensitive: bool = False,
    model: str = "ai-gateway/auto",   # or ai-gateway/small | mid | frontier to pin a tier
    min_tier: str | None = None,
    max_tier: str | None = None,
    run_max_budget: float | None = None,   # USD cap; fixed by the run's FIRST call
    run_max_steps: int | None = None,      # step cap; fixed by the run's FIRST call
    temperature: float = 0.0,              # <= 0.05 makes the call cacheable
) -> ChatOpenAI:
    headers = {"X-App-Id": APP_ID, "X-Agent": agent, "X-Run-Id": run_id, "X-Step": str(step)}
    if sensitive:
        headers["X-Sensitivity"] = "true"   # set from your PII / data-classification check
    if min_tier:
        headers["X-Min-Tier"] = min_tier
    if max_tier:
        headers["X-Max-Tier"] = max_tier
    if run_max_budget is not None:
        headers["X-Run-Max-Budget"] = str(run_max_budget)
    if run_max_steps is not None:
        headers["X-Run-Max-Steps"] = str(run_max_steps)
    return ChatOpenAI(
        model=model,
        base_url=GATEWAY_URL,
        api_key=GATEWAY_KEY,
        temperature=temperature,
        include_response_headers=True,   # lets us read the routing decision back
        default_headers=headers,
    )


def _message(e: Exception) -> str:
    body = getattr(e, "body", None)
    try:
        return body["detail"]["error"]["message"]
    except Exception:  # noqa: BLE001 - fall back to the raw error text
        return str(e)


def invoke_guarded(llm, messages):
    """Call the model; return (AIMessage, routing_dict). Raises GatewayBlocked
    or PolicyBlocked for the gateway's permanent rejections."""
    try:
        msg = llm.invoke(messages)
    except openai.RateLimitError as e:
        raise GatewayBlocked(_message(e)) from e
    except openai.PermissionDeniedError as e:
        raise PolicyBlocked(_message(e)) from e
    headers = msg.response_metadata.get("headers", {})
    routing = {k[len("x-ai-gateway-"):]: v for k, v in headers.items() if k.lower().startswith("x-ai-gateway-")}
    return msg, routing
