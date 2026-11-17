from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider: str = "unknown"
    model: str = "unknown"

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, history: list[dict], model: str, max_output_tokens: int) -> ModelResponse:
        raise NotImplementedError
