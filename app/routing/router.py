from dataclasses import dataclass
from time import monotonic
from threading import Lock

@dataclass
class ModelProfile:
    provider: str
    model: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    quality_score: float
    latency_score: float
    capabilities: set[str]
    enabled: bool = True

@dataclass
class RouteDecision:
    provider: str
    model: str
    reason: str
    score: float

class ProviderHealth:
    def __init__(self, failure_threshold=3, recovery_seconds=30):
        self.failure_threshold=failure_threshold; self.recovery_seconds=recovery_seconds
        self._lock=Lock(); self._state={}
    def _get(self,key): return self._state.setdefault(key, {'failures':0,'opened_at':None,'latency_ms':0.0})
    def record_success(self,key,latency_ms):
        with self._lock:
            s=self._get(key); s['failures']=0; s['opened_at']=None; s['latency_ms']=latency_ms
    def record_failure(self,key):
        with self._lock:
            s=self._get(key); s['failures']+=1
            if s['failures']>=self.failure_threshold and s['opened_at'] is None: s['opened_at']=monotonic()
    def available(self,key):
        with self._lock:
            s=self._get(key)
            if s['opened_at'] is None: return True
            if monotonic()-s['opened_at'] >= self.recovery_seconds:
                s['opened_at']=None; s['failures']=0; return True
            return False
    def snapshot(self):
        with self._lock: return {k: dict(v) for k,v in self._state.items()}

class IntelligentRouter:
    def __init__(self, profiles, health=None):
        self.profiles=profiles; self.health=health or ProviderHealth()
    def rank(self, task_type='general', priority='balanced', max_cost=None, required_capabilities=None):
        required=set(required_capabilities or [])
        candidates=[]
        for p in self.profiles:
            key=f'{p.provider}:{p.model}'
            if not p.enabled or not self.health.available(key): continue
            if required and not required.issubset(p.capabilities): continue
            if max_cost is not None and p.cost_per_1k_input > max_cost: continue
            capability_bonus=1.0 if task_type in p.capabilities else 0.0
            if priority=='quality': score=p.quality_score*2 + p.latency_score*.25 + capability_bonus
            elif priority=='latency': score=p.latency_score*2 + p.quality_score*.25 + capability_bonus
            elif priority=='cost': score=(1/(1+p.cost_per_1k_input))*3 + p.quality_score*.1 + capability_bonus
            else: score=p.quality_score + p.latency_score + capability_bonus
            candidates.append((score,p))
        if not candidates: raise RuntimeError('NO_HEALTHY_MODEL_AVAILABLE')
        return sorted(candidates,key=lambda x:x[0],reverse=True)
    def choose(self, task_type='general', priority='balanced', max_cost=None, required_capabilities=None):
        score,p=self.rank(task_type,priority,max_cost,required_capabilities)[0]
        return RouteDecision(p.provider,p.model,f'priority={priority};task={task_type}',score)
