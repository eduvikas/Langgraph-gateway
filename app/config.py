from functools import lru_cache
import os
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()
class Settings(BaseModel):
    app_name:str=os.getenv('APP_NAME','langgraph-gateway-v2.6')
    app_env:str=os.getenv('APP_ENV','local'); log_level:str=os.getenv('LOG_LEVEL','INFO')
    openai_api_key:str=os.getenv('OPENAI_API_KEY',''); openai_model:str=os.getenv('OPENAI_MODEL','gpt-5.6-sol')
    max_prompt_chars:int=int(os.getenv('MAX_PROMPT_CHARS','20000')); max_output_tokens:int=int(os.getenv('MAX_OUTPUT_TOKENS','2000'))
    max_requests_per_session:int=int(os.getenv('MAX_REQUESTS_PER_SESSION','50'))
    rate_limit_requests:int=int(os.getenv('RATE_LIMIT_REQUESTS','60')); rate_limit_window_seconds:int=int(os.getenv('RATE_LIMIT_WINDOW_SECONDS','60'))
    database_url:str=os.getenv('DATABASE_URL','sqlite:///./gateway.db'); memory_backend:str=os.getenv('MEMORY_BACKEND','sql')
    rate_limiter_backend:str=os.getenv('RATE_LIMITER_BACKEND','memory'); redis_url:str=os.getenv('REDIS_URL','redis://localhost:6379/0')
    policy_file:str=os.getenv('POLICY_FILE','config/policies.json'); auth_enabled:bool=os.getenv('AUTH_ENABLED','false').lower()=='true'
    jwt_secret:str=os.getenv('JWT_SECRET','change-me-in-production'); jwt_algorithm:str=os.getenv('JWT_ALGORITHM','HS256'); jwt_issuer:str=os.getenv('JWT_ISSUER',''); jwt_audience:str=os.getenv('JWT_AUDIENCE','')
    allow_insecure_local_auth:bool=os.getenv('ALLOW_INSECURE_LOCAL_AUTH','true').lower()=='true'; block_secrets:bool=os.getenv('BLOCK_SECRETS','true').lower()=='true'; block_prompt_injection:bool=os.getenv('BLOCK_PROMPT_INJECTION','true').lower()=='true'
    routing_priority:str=os.getenv('ROUTING_PRIORITY','balanced'); routing_task:str=os.getenv('ROUTING_TASK','general'); mock_provider_enabled:bool=os.getenv('MOCK_PROVIDER_ENABLED','true').lower()=='true'
    circuit_failure_threshold:int=int(os.getenv('CIRCUIT_FAILURE_THRESHOLD','3')); circuit_recovery_seconds:int=int(os.getenv('CIRCUIT_RECOVERY_SECONDS','30'))
    evaluation_enabled:bool=os.getenv('EVALUATION_ENABLED','true').lower()=='true'; evaluation_min_score:float=float(os.getenv('EVALUATION_MIN_SCORE','0.65'))
    allowed_applications_raw:str=os.getenv('ALLOWED_APPLICATIONS','demo-app,contract-agent,sre-agent'); allowed_models_raw:str=os.getenv('ALLOWED_MODELS','gpt-5.6-sol,gpt-6-sol,gpt-6-luna')
    @property
    def allowed_applications(self): return {x.strip() for x in self.allowed_applications_raw.split(',') if x.strip()}
    @property
    def allowed_models(self): return {x.strip() for x in self.allowed_models_raw.split(',') if x.strip()}
@lru_cache
def get_settings(): return Settings()
