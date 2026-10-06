from openai import OpenAI
from app.providers.base import LLMProvider, ModelResponse

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self.client = OpenAI(api_key=api_key)

    def generate(self, prompt: str, history: list[dict], model: str, max_output_tokens: int) -> ModelResponse:
        input_items = list(history) + [{"role": "user", "content": prompt}]
        response = self.client.responses.create(
            model=model,
            input=input_items,
            max_output_tokens=max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        return ModelResponse(
            text=response.output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            provider="openai",
            model=model,
        )
