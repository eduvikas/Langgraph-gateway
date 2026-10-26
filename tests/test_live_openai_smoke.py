"""Opt-in live provider smoke test. It spends API credits; disabled by default."""
import os
import pytest

@pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1", reason="Set RUN_LIVE_PROVIDER_TESTS=1 to run a billable provider smoke test")
def test_live_openai_returns_provider_usage():
    from app.providers.openai_provider import OpenAIProvider
    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not key or not model:
        pytest.skip("OPENAI_API_KEY and OPENAI_MODEL are required")
    result = OpenAIProvider(key).generate("Reply with the word OK.", [], model, 16)
    assert result.text
    assert result.input_tokens > 0
    assert result.output_tokens >= 0
    assert result.total_tokens >= result.input_tokens + result.output_tokens
