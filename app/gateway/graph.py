from time import perf_counter
from hashlib import sha256
from langgraph.graph import StateGraph, START, END
from app.observability.logging import get_logger
from app.providers.factory import get_provider
from app.gateway.state import GatewayState
from app.security.identity import IdentityProvider
from app.security.content import ContentSecurityEngine
from app.routing.router import IntelligentRouter, ModelProfile, ProviderHealth, build_provider_health
from app.routing.classifier import classify_request
from app.evaluation.engine import EvaluationEngine
from app.evaluation.store import store as evaluation_store
from app.security.policy import classification_allowed
logger=get_logger(__name__)

def budget_reservation_key(request_id, provider, model):
    """Stable, bounded SQL key independent of caller-supplied request ID length."""
    digest = sha256(f"{request_id}|{provider}|{model}".encode("utf-8")).hexdigest()
    return "br_" + digest

# Prices live in app/economics/pricing.py; PRICING and estimate_cost stay importable from here.
from app.economics.pricing import PRICING, cost_usd as estimate_cost, price_call
from app.economics.cache import make_cache_key, skip_reason as cache_skip_reason

def build_gateway_graph(settings,memory,governance,rate_limiter,audit,budget=None,cache=None):
    identity_provider=IdentityProvider(settings); security=ContentSecurityEngine(strict_injection=settings.injection_strict); health=build_provider_health(settings)
    profiles=[]
    if settings.model_profiles_json:
        import json
        for item in json.loads(settings.model_profiles_json):
            _prices = PRICING.get(item['model'], (0.0, 0.0))
            profiles.append(ModelProfile(item['provider'], item['model'], float(_prices[0]), float(_prices[1]), float(item.get('quality', .8)), float(item.get('latency', .8)), set(item.get('capabilities', ['general'])), bool(item.get('enabled', True))))
    elif settings.openai_api_key:
        profiles=[ModelProfile('openai','gpt-5.6-sol',*PRICING.get('gpt-5.6-sol',(0,0)),0.95,0.70,{'general','reasoning','coding'}),ModelProfile('openai','gpt-5.6-terra',*PRICING.get('gpt-5.6-terra',(0,0)),0.92,0.82,{'general','reasoning','coding'}),ModelProfile('openai','gpt-5.6-luna',*PRICING.get('gpt-5.6-luna',(0,0)),0.82,0.96,{'general','general_fast'})]
    if settings.mock_provider_enabled and not any(p.provider == 'mock' for p in profiles): profiles.append(ModelProfile('mock','mock-general',0,0,.40,1.0,{'general','general_fast'}))
    router=IntelligentRouter(profiles,health); evaluator=EvaluationEngine()
    def identity_node(state):
        identity=identity_provider.authenticate(state.get('authorization'),state.get('user_id',''),state['application_id'])
        return {'user_id':identity.user_id,'roles':identity.roles,'authenticated':identity.authenticated}
    def security_node(state):
        assessment=security.assess(state['prompt']); findings=[{'category':f.category,'pattern':f.pattern,'severity':f.severity} for f in assessment.findings]
        return {'data_classification':assessment.classification,'security_findings':findings,'security_reason':assessment.reason or ''}
    def governance_node(state):
        count=memory.increment_request_count(state['session_id'],state['user_id'],state['application_id']); allowed_rate,remaining=rate_limiter.allow(f"user:{state['user_id']}")
        classification = classify_request(state['prompt'], state.get('routing_metadata'))
        policy = governance.policy_store.get(state['application_id'])
        allowed_models = set(policy.allowed_models or settings.allowed_models)
        eligible_profiles = [p for p in profiles if p.model in allowed_models and p.enabled]
        request_router = IntelligentRouter(eligible_profiles, health)
        try:
            ranked = request_router.rank(classification.task_type, classification.priority,
                                         required_capabilities=classification.required_capabilities)
        except RuntimeError:
            return {'decision':'BLOCK','block_reason':'NO_ELIGIBLE_MODEL','request_count':count,
                    'rate_remaining':remaining,'task_type':classification.task_type,
                    'routing_priority':classification.priority,'routing_reason':classification.reason}
        candidates = [{'provider':p.provider,'model':p.model,'score':score} for score,p in ranked]
        route = candidates[0]
        d=governance.evaluate(state['application_id'],route['model'],state['prompt'],count,allowed_rate,
                              state.get('roles',set()),state.get('data_classification','internal'),
                              state.get('security_reason') or None,
                              has_pii=any(f['category']=='PII' for f in state.get('security_findings',[])))
        return {'decision':'ALLOW' if d.allowed else 'BLOCK','block_reason':d.reason or '',
                'request_count':count,'rate_remaining':remaining,'selected_provider':route['provider'],
                'selected_model':route['model'],'routing_selected_provider':route['provider'],'routing_selected_model':route['model'],'route_reason':f"task={classification.task_type};priority={classification.priority};{classification.reason}",
                'route_score':route['score'],'routing_candidates':candidates,'task_type':classification.task_type,
                'routing_priority':classification.priority,'routing_reason':classification.reason,
                'estimated_complexity':classification.estimated_complexity,'required_capabilities':sorted(classification.required_capabilities)}
    def memory_node(state): return {'history':memory.get_history(state['session_id'],state['user_id'])}
    def cache_lookup_node(state):
        # Runs AFTER governance, so a cached answer never bypasses identity, roles, rate limits or security rules.
        if cache is None: return {'cache_hit':False}
        reason=cache_skip_reason(governance.policy_store.get(state['application_id']),state)
        if reason: return {'cache_hit':False,'cache_skip':reason}
        key=make_cache_key(state['application_id'],state['selected_model'],state['prompt'],state.get('history',[])); entry=cache.get(key)
        return {'cache_key':key,'cache_hit':True,'cache_entry':entry} if entry else {'cache_key':key,'cache_hit':False}
    def route_after_cache(state): return 'hit' if state.get('cache_hit') else 'miss'
    def cache_serve_node(state):
        e=state['cache_entry']
        memory.append(state['session_id'],'user',state['prompt'],state['user_id'],state['application_id']); memory.append(state['session_id'],'assistant',e['response'],state['user_id'],state['application_id'])
        would=price_call(settings,e['provider'],e['model'],e['input_tokens'],e['output_tokens'])   # what this call would have cost
        return {'selected_provider':e['provider'],'selected_model':e['model'],'failed_models':[],'response':e['response'],'input_tokens':0,'output_tokens':0,'total_tokens':0,'tokens_avoided':e['total_tokens'],'cache_hit':True,'cost_usd':0.0,'estimated_cost_usd':0.0,'baseline_cost_usd':would.baseline_cost_usd,'avoided_cost_usd':would.cost_usd,'billable':would.billable,'priced':would.priced,'evaluation':e['evaluation']}
    def budget_node(state):
        # Reserve the estimated spend atomically before the provider call.
        if budget is None:
            return {}
        breakdown = budget.estimate_breakdown(state['selected_provider'], state['selected_model'], state['prompt'], state.get('history', []))
        status = budget.status(state['application_id'])
        if not status.get('unlimited') and not breakdown.priced and state['selected_provider'] != 'mock':
            return {'decision':'BLOCK','block_reason':'UNPRICED_MODEL','budget':status,'priced':False,'estimated_cost_usd':None}
        reservation_id = budget_reservation_key(state['request_id'], state['selected_provider'], state['selected_model'])
        if status.get('unlimited'):
            return {'budget':status,'preflight_estimated_cost_usd':breakdown.cost_usd,'estimated_cost_usd':breakdown.cost_usd}
        allowed, status = budget.reserve(state['application_id'], reservation_id, breakdown.cost_usd)
        if not allowed:
            return {'decision':'BLOCK','block_reason':'BUDGET_EXCEEDED','budget':status,'preflight_estimated_cost_usd':breakdown.cost_usd}
        return {'budget':status,'preflight_estimated_cost_usd':breakdown.cost_usd,'estimated_cost_usd':breakdown.cost_usd,'budget_reservation_id':reservation_id}

    def execute_node(state):
        # The approved model is attempted first. Each failover candidate gets its own reservation.
        by_key = {(p.provider, p.model): p for p in profiles}
        candidates = state.get('routing_candidates') or [{'provider':state['selected_provider'],'model':state['selected_model'],'score':state.get('route_score',0)}]
        last_error = None; result = None; used = None; failed = []
        reservation_id = state.get('budget_reservation_id')
        initial_key = (state.get('selected_provider'), state.get('selected_model'))
        for candidate in candidates:
            profile = by_key.get((candidate['provider'], candidate['model']))
            if profile is None:
                continue
            candidate_key = (profile.provider, profile.model)
            if budget is not None and budget.limit_for(state['application_id']) is not None:
                if candidate_key != initial_key:
                    if reservation_id:
                        budget.release(reservation_id); reservation_id = None
                    breakdown = budget.estimate_breakdown(profile.provider, profile.model, state['prompt'], state.get('history', []))
                    if not breakdown.priced and profile.provider != 'mock':
                        failed.append(profile.model + ':UNPRICED_MODEL'); continue
                    reservation_id = budget_reservation_key(state['request_id'], profile.provider, profile.model)
                    allowed, _ = budget.reserve(state['application_id'], reservation_id, breakdown.cost_usd)
                    if not allowed:
                        reservation_id = None; failed.append(profile.model + ':BUDGET_EXCEEDED'); continue
            
            if budget is not None and budget.limit_for(state['application_id']) is not None:
                final_breakdown = budget.estimate_breakdown(profile.provider, profile.model, state['prompt'], state.get('history', []))
                execution_estimate = final_breakdown.cost_usd if final_breakdown.priced else None
            else:
                execution_estimate = state.get('preflight_estimated_cost_usd')
            key = f"{profile.provider}:{profile.model}"; started = perf_counter()
            try:
                provider = get_provider(settings, profile.provider)
                result = provider.generate(prompt=state['prompt'], history=state.get('history', []), model=profile.model, max_output_tokens=settings.max_output_tokens)
                if result.model != profile.model:
                    raise RuntimeError(f"PROVIDER_MODEL_MISMATCH: requested {profile.model}, received {result.model}")
                if profile.provider != 'mock' and (result.input_tokens <= 0 or result.output_tokens < 0 or result.total_tokens < result.input_tokens + result.output_tokens):
                    raise RuntimeError('PROVIDER_USAGE_INVALID')
                health.record_success(key, (perf_counter()-started)*1000); used = profile
                break
            except Exception as exc:
                health.record_failure(key); last_error = exc; failed.append(profile.model)
                if budget is not None and reservation_id:
                    budget.release(reservation_id); reservation_id = None
        if result is None:
            if budget is not None and reservation_id:
                budget.release(reservation_id)
            raise RuntimeError(f"ALL_MODELS_FAILED: {last_error or 'no allowed model available'}")
        memory.append(state['session_id'],'user',state['prompt'],state['user_id'],state['application_id'])
        memory.append(state['session_id'],'assistant',result.text,state['user_id'],state['application_id'])
        priced = price_call(settings, used.provider, result.model, result.input_tokens, result.output_tokens)
        if used.provider != 'mock' and not priced.priced:
            logger.error('provider_model_price_unverified', extra={'request_id':state['request_id'], 'provider':used.provider, 'model':result.model})
        if budget is not None and reservation_id:
            # If the provider resolved an alias to an unpriced model, release the estimate but
            # mark the ledger row unpriced; never fabricate a zero-dollar actual cost.
            budget.settle(reservation_id, priced.cost_usd if priced.priced else None)
        evaluation = evaluator.evaluate(state['prompt'], result.text, state.get('security_findings', []))
        evaluation_store.record(request_id=state['request_id'],model=result.model,provider=result.provider,overall=evaluation.overall,passed=evaluation.passed,reasons=evaluation.reasons)
        if cache is not None and state.get('cache_key') and evaluation.passed:
            cache.set(state['cache_key'], {'response':result.text,'provider':used.provider,'model':result.model,'input_tokens':result.input_tokens,'output_tokens':result.output_tokens,'total_tokens':result.total_tokens,'evaluation':evaluation.__dict__})
        return {'selected_provider':used.provider,'selected_model':result.model,'failed_models':failed,'response':result.text,'input_tokens':result.input_tokens,'output_tokens':result.output_tokens,'total_tokens':result.total_tokens,'cache_hit':False,'tokens_avoided':0,'avoided_cost_usd':0.0,'cost_usd':priced.cost_usd,'baseline_cost_usd':priced.baseline_cost_usd,'billable':priced.billable,'priced':priced.priced,'pricing_warning':None if priced.priced or used.provider == 'mock' else 'Provider returned a model without a verified price entry','estimated_cost_usd':execution_estimate if execution_estimate is not None else priced.cost_usd,'preflight_estimated_cost_usd':execution_estimate,'final_budget_reservation_id':reservation_id,'evaluation':evaluation.__dict__}
    def _routing_audit_payload(state):
        # Preserve the original decision separately from the final model used after failover.
        return {
            'task_classification': {
                'task_type': state.get('task_type'),
                'priority': state.get('routing_priority'),
                'estimated_complexity': state.get('estimated_complexity'),
                'required_capabilities': state.get('required_capabilities', []),
            },
            'routing_priority': state.get('routing_priority'),
            'data_classification': state.get('data_classification', 'internal'),
            'selected_model': state.get('routing_selected_model') or state.get('selected_model'),
            'selected_provider': state.get('routing_selected_provider') or state.get('selected_provider'),
            'ranked_alternatives': state.get('routing_candidates', []),
            'routing_reason': state.get('route_reason') or state.get('routing_reason'),
            'routing_score': state.get('route_score'),
            'estimated_cost_usd': state.get('preflight_estimated_cost_usd', state.get('estimated_cost_usd')),
            'reservation_id': state.get('final_budget_reservation_id') or state.get('budget_reservation_id'),
            'final_executed_model': state.get('selected_model') if state.get('response') is not None else None,
            'final_executed_provider': state.get('selected_provider') if state.get('response') is not None else None,
            'failed_models': state.get('failed_models', []),
            'cache_hit': bool(state.get('cache_hit', False)),
            'block_reason': state.get('block_reason'),
        }
    def finalize_node(state):
        audit.record(event_type='CHAT_COMPLETED',request_id=state['request_id'],user_id=state['user_id'],application_id=state['application_id'],session_id=state['session_id'],outcome=state.get('decision','UNKNOWN'),classification=state.get('data_classification','internal'),details=state.get('block_reason') or None,routing_decision=_routing_audit_payload(state))
        logger.info('gateway_completed',extra={'request_id':state['request_id']}); return {}
    def blocked_node(state):
        audit.record(event_type='GOVERNANCE_BLOCK',request_id=state['request_id'],user_id=state.get('user_id','unknown'),application_id=state['application_id'],session_id=state['session_id'],outcome=state.get('block_reason','BLOCK'),classification=state.get('data_classification','internal'),details=str(state.get('security_findings',[])),routing_decision=_routing_audit_payload(state)); return {}
    def route_after_governance(state): return 'blocked' if state.get('decision')=='BLOCK' else 'allowed'
    graph=StateGraph(GatewayState)
    for name,node in [('identity',identity_node),('security',security_node),('governance',governance_node),('memory',memory_node),('cache_lookup',cache_lookup_node),('cache_serve',cache_serve_node),('budget',budget_node),('execute',execute_node),('finalize',finalize_node),('blocked',blocked_node)]: graph.add_node(name,node)
    graph.add_edge(START,'identity'); graph.add_edge('identity','security'); graph.add_edge('security','governance'); graph.add_conditional_edges('governance',route_after_governance,{'blocked':'blocked','allowed':'memory'}); graph.add_edge('blocked',END); graph.add_edge('memory','cache_lookup'); graph.add_conditional_edges('cache_lookup',route_after_cache,{'hit':'cache_serve','miss':'budget'}); graph.add_edge('cache_serve','finalize'); graph.add_conditional_edges('budget',route_after_governance,{'blocked':'blocked','allowed':'execute'}); graph.add_edge('execute','finalize'); graph.add_edge('finalize',END)
    return graph.compile(), health
