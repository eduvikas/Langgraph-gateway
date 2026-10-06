from time import perf_counter
from langgraph.graph import StateGraph, START, END
from app.observability.logging import get_logger
from app.providers.factory import get_provider
from app.gateway.state import GatewayState
from app.security.identity import IdentityProvider
from app.security.content import ContentSecurityEngine
from app.routing.router import IntelligentRouter, ModelProfile, ProviderHealth
from app.evaluation.engine import EvaluationEngine
from app.evaluation.store import store as evaluation_store
from app.security.policy import classification_allowed
logger=get_logger(__name__)

PRICING={'gpt-5.6-sol':(4.0,20.0),'gpt-6-sol':(1.0,5.0),'gpt-6-luna':(.05,.25),'mock-general':(0,0)}
def estimate_cost(model,inp,out):
    a,b=PRICING.get(model,(0,0)); return round(inp*a/1_000_000+out*b/1_000_000,8)

def build_gateway_graph(settings,memory,governance,rate_limiter,audit):
    identity_provider=IdentityProvider(settings); security=ContentSecurityEngine(); health=ProviderHealth(settings.circuit_failure_threshold,settings.circuit_recovery_seconds)
    profiles=[]
    if settings.openai_api_key:
        profiles=[ModelProfile('openai','gpt-5.6-sol',4,20,0.95,0.70,{'general','reasoning','coding'}),ModelProfile('openai','gpt-6-sol',1,5,0.92,0.82,{'general','reasoning','coding'}),ModelProfile('openai','gpt-6-luna',.05,.25,0.82,0.96,{'general','general_fast'})]
    if settings.mock_provider_enabled: profiles.append(ModelProfile('mock','mock-general',0,0,.40,1.0,{'general','general_fast'}))
    router=IntelligentRouter(profiles,health); evaluator=EvaluationEngine()
    def identity_node(state):
        identity=identity_provider.authenticate(state.get('authorization'),state.get('user_id',''),state['application_id'])
        return {'user_id':identity.user_id,'roles':identity.roles,'authenticated':identity.authenticated}
    def security_node(state):
        assessment=security.assess(state['prompt']); findings=[{'category':f.category,'pattern':f.pattern,'severity':f.severity} for f in assessment.findings]
        return {'data_classification':assessment.classification,'security_findings':findings,'security_reason':assessment.reason or ''}
    def governance_node(state):
        count=memory.increment_request_count(state['session_id'],state['user_id'],state['application_id']); allowed_rate,remaining=rate_limiter.allow(f"user:{state['user_id']}")
        route=router.choose(settings.routing_task,settings.routing_priority)
        d=governance.evaluate(state['application_id'],route.model,state['prompt'],count,allowed_rate,state.get('roles',set()),state.get('data_classification','internal'),state.get('security_reason') or None)
        return {'decision':'ALLOW' if d.allowed else 'BLOCK','block_reason':d.reason or '','request_count':count,'rate_remaining':remaining,'selected_provider':route.provider,'selected_model':route.model,'route_reason':route.reason,'route_score':route.score}
    def memory_node(state): return {'history':memory.get_history(state['session_id'],state['user_id'])}
    def execute_node(state):
        ranked=router.rank(settings.routing_task,settings.routing_priority)
        last_error=None
        result=None
        for _,profile in ranked:
            key=f"{profile.provider}:{profile.model}"; started=perf_counter()
            try:
                provider=get_provider(settings,profile.provider); result=provider.generate(prompt=state['prompt'],history=state.get('history',[]),model=profile.model,max_output_tokens=settings.max_output_tokens)
                health.record_success(key,(perf_counter()-started)*1000)
                state['selected_provider']=profile.provider; state['selected_model']=profile.model
                break
            except Exception as exc:
                health.record_failure(key); last_error=exc
        if result is None: raise RuntimeError(f'ALL_MODELS_FAILED: {last_error}')
        memory.append(state['session_id'],'user',state['prompt'],state['user_id'],state['application_id']); memory.append(state['session_id'],'assistant',result.text,state['user_id'],state['application_id'])
        cost=estimate_cost(result.model,result.input_tokens,result.output_tokens)
        evaluation=evaluator.evaluate(state['prompt'],result.text,state.get('security_findings',[]))
        evaluation_store.record(request_id=state['request_id'],model=result.model,provider=result.provider,overall=evaluation.overall,passed=evaluation.passed,reasons=evaluation.reasons)
        return {'response':result.text,'input_tokens':result.input_tokens,'output_tokens':result.output_tokens,'total_tokens':result.total_tokens,'cache_hit':False,'estimated_cost_usd':cost,'evaluation':evaluation.__dict__}
    def finalize_node(state):
        audit.record(event_type='CHAT_COMPLETED',request_id=state['request_id'],user_id=state['user_id'],application_id=state['application_id'],session_id=state['session_id'],outcome=state.get('decision','UNKNOWN'),classification=state.get('data_classification','internal'),details=state.get('block_reason') or None)
        logger.info('gateway_completed',extra={'request_id':state['request_id']}); return {}
    def blocked_node(state):
        audit.record(event_type='GOVERNANCE_BLOCK',request_id=state['request_id'],user_id=state.get('user_id','unknown'),application_id=state['application_id'],session_id=state['session_id'],outcome=state.get('block_reason','BLOCK'),classification=state.get('data_classification','internal'),details=str(state.get('security_findings',[]))); return {}
    def route_after_governance(state): return 'blocked' if state.get('decision')=='BLOCK' else 'allowed'
    graph=StateGraph(GatewayState)
    for name,node in [('identity',identity_node),('security',security_node),('governance',governance_node),('memory',memory_node),('execute',execute_node),('finalize',finalize_node),('blocked',blocked_node)]: graph.add_node(name,node)
    graph.add_edge(START,'identity'); graph.add_edge('identity','security'); graph.add_edge('security','governance'); graph.add_conditional_edges('governance',route_after_governance,{'blocked':'blocked','allowed':'memory'}); graph.add_edge('blocked',END); graph.add_edge('memory','execute'); graph.add_edge('execute','finalize'); graph.add_edge('finalize',END)
    return graph.compile(), health
