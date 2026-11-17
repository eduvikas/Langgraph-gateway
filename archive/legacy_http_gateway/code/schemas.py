"""
Pydantic models matching OpenAI's /v1/chat/completions shape closely
enough that the real `openai` Python SDK, LangChain's ChatOpenAI, and most
agent frameworks can point at this service by changing only base_url and
api_key. Fields AI Gateway doesn't act on (tool_choice specifics, logprobs,
n>1, etc.) are accepted so requests don't fail validation, but only a
useful subset is actually implemented — see server.py and the README for
exactly what that subset is.
"""
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ToolFunction(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[dict] = None


class Tool(BaseModel):
    type: Literal["function"] = "function"
    function: ToolFunction


class ChatCompletionRequest(BaseModel):
    model: str = "ai-gateway/auto"
    messages: list[ChatMessage]
    tools: Optional[list[Tool]] = None
    tool_choice: Optional[Union[str, dict]] = None
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    # AI Gateway routing context can travel here instead of headers, for
    # clients that can't easily set custom headers.
    metadata: Optional[dict[str, Any]] = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "ai-gateway"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]
