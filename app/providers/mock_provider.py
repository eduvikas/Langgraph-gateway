from app.providers.base import LLMProvider, ModelResponse
class MockProvider(LLMProvider):
    def __init__(self, prefix='mock'): self.prefix=prefix
    def generate(self,prompt,history,model,max_output_tokens):
        text=f'[MOCK:{model}] {prompt[:500]}'
        return ModelResponse(text=text,input_tokens=max(1,len(prompt)//4),output_tokens=max(1,len(text)//4),total_tokens=max(2,len(prompt)//4+len(text)//4),provider='mock',model=model)
