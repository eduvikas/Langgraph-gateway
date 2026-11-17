from types import SimpleNamespace
import pytest
pytest.importorskip("openai")
import app.providers.openai_provider as module
from app.providers.openai_provider import OpenAIProvider

def fake_openai(monkeypatch, response):
    class Responses:
        def create(self, **kwargs): return response
    class Client:
        def __init__(self, **kwargs): self.responses = Responses()
    monkeypatch.setattr(module, "OpenAI", Client)

def test_provider_uses_reported_model_and_usage(monkeypatch):
    fake_openai(monkeypatch, SimpleNamespace(output_text="OK", model="model-snapshot-2026", usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6)))
    result = OpenAIProvider("test-key", timeout=1).generate("hi", [], "model-snapshot-2026", 10)
    assert result.model == "model-snapshot-2026"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (4, 2, 6)

def test_provider_fails_closed_when_usage_is_missing(monkeypatch):
    fake_openai(monkeypatch, SimpleNamespace(output_text="OK", model="model-x", usage=None))
    with pytest.raises(RuntimeError, match="PROVIDER_USAGE_MISSING"):
        OpenAIProvider("test-key", timeout=1).generate("hi", [], "model-x", 10)

def test_provider_fails_closed_when_usage_counts_are_invalid(monkeypatch):
    fake_openai(monkeypatch, SimpleNamespace(output_text="OK", model="model-x", usage=SimpleNamespace(input_tokens=-1, output_tokens=2, total_tokens=1)))
    with pytest.raises(RuntimeError, match="PROVIDER_USAGE_INVALID"):
        OpenAIProvider("test-key", timeout=1).generate("hi", [], "model-x", 10)
