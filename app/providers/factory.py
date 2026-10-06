from app.config import Settings
from app.providers.openai_provider import OpenAIProvider
from app.providers.mock_provider import MockProvider

def get_provider(settings: Settings, provider_name='openai'):
    if provider_name=='openai': return OpenAIProvider(settings.openai_api_key)
    if provider_name=='mock': return MockProvider()
    raise ValueError(f'Unsupported provider: {provider_name}')
