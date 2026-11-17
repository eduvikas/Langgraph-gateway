from openai import OpenAI
from app.providers.base import LLMProvider, ModelResponse

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, timeout: float = 60.0):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    def generate(self, prompt: str, history: list[dict], model: str, max_output_tokens: int) -> ModelResponse:
        input_items = list(history) + [{"role": "user", "content": prompt}]
        response = self.client.responses.create(
            model=model,
            input=input_items,
            max_output_tokens=max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        if usage is None or getattr(usage, "input_tokens", None) is None or getattr(usage, "output_tokens", None) is None:
            raise RuntimeError("PROVIDER_USAGE_MISSING: refusing to report unverified token economics")
        input_tokens = int(usage.input_tokens)
        output_tokens = int(usage.output_tokens)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        if input_tokens < 0 or output_tokens < 0 or total_tokens < input_tokens + output_tokens:
            raise RuntimeError("PROVIDER_USAGE_INVALID")
        return ModelResponse(
            text=response.output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            provider="openai",
            model=getattr(response, "model", None) or model,
        )
