from app.routing.router import IntelligentRouter, ModelProfile, ProviderHealth
from app.evaluation.engine import EvaluationEngine

def test_router_prefers_low_cost_when_requested():
    r=IntelligentRouter([ModelProfile('a','expensive',10,10,.99,.5,{'general'}),ModelProfile('b','cheap',.1,.1,.8,.8,{'general'})])
    d=r.choose(priority='cost'); assert d.model=='cheap'

def test_circuit_breaker_opens():
    h=ProviderHealth(failure_threshold=2,recovery_seconds=999)
    h.record_failure('x'); assert h.available('x')
    h.record_failure('x'); assert not h.available('x')

def test_router_skips_open_circuit():
    h=ProviderHealth(failure_threshold=1,recovery_seconds=999); h.record_failure('a:a')
    r=IntelligentRouter([ModelProfile('a','a',1,1,.9,.9,{'general'}),ModelProfile('b','b',2,2,.8,.8,{'general'})],h)
    assert r.choose().provider=='b'

def test_evaluation_flags_irrelevant_response():
    e=EvaluationEngine().evaluate('Explain incident severity', 'blue banana table')
    assert not e.passed or 'LOW_RELEVANCE' in e.reasons

def test_evaluation_accepts_relevant_response():
    e=EvaluationEngine().evaluate('Explain incident severity', 'Incident severity indicates the impact and urgency of an incident.')
    assert e.overall>=.65
