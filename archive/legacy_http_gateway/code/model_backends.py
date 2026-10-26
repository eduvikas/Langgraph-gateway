"""
Model backends for the gateway.

With no setup, every tier is mocked (FakeListChatModel) — the whole gateway
runs with zero API keys.

Set OPENAI_API_KEY and the gateway automatically routes real calls to
OpenAI instead, one model per tier, and the cost calculation switches from
the pre-classified token estimate to the model's actual reported usage
(see call_model() in gateway_graph.py) — the same routing and guardrail
logic, just backed by real models and real token counts.

ANTHROPIC_API_KEY works the same way if you'd rather point this at Claude.
If both are set, OpenAI is used — change PROVIDER below to flip that.
"""
import os

from langchain_core.language_models.fake_chat_models import FakeListChatModel

OPENAI_KEY_SET = bool(os.environ.get("OPENAI_API_KEY"))
ANTHROPIC_KEY_SET = bool(os.environ.get("ANTHROPIC_API_KEY"))
REAL_MODELS_ENABLED = OPENAI_KEY_SET or ANTHROPIC_KEY_SET

# Which provider to use when a key is available. "openai" (default) picks
# OpenAI first if both keys happen to be set; swap to "anthropic" to prefer
# Claude instead.
PROVIDER = "openai" if OPENAI_KEY_SET else "anthropic"

# Maps gateway tiers to real models, one map per provider. Swap any of
# these freely — point "small" at a self-hosted open model, "mid" at a
# different provider, whatever your real stack looks like. The gateway's
# routing and guardrail logic doesn't care what's behind each tier.
TIER_TO_MODEL = {
    "openai": {
        "small":    "gpt-4.1-nano",
        "mid":      "gpt-4.1-mini",
        "frontier": "gpt-5.1",
    },
    "anthropic": {
        "small":    "claude-haiku-4-5-20251001",
        "mid":      "claude-sonnet-5",
        "frontier": "claude-opus-5",
    },
}


def make_model(tier: str):
    if REAL_MODELS_ENABLED:
        # max_tokens kept small on purpose — this is a routing demo, not a
        # place to run up a real bill. Raise it once you're past the demo.
        if PROVIDER == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=TIER_TO_MODEL["openai"][tier], max_completion_tokens=60, temperature=0)
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=TIER_TO_MODEL["anthropic"][tier], max_tokens=60, temperature=0)
    return FakeListChatModel(responses=[f"[{tier} model response]"])
