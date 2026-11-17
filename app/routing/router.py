from dataclasses import dataclass
from time import monotonic
from threading import Lock

@dataclass
class ModelProfile:
    provider: str
    model: str
    cost_per_1m_input: float
    cost_per_1m_output: float
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
            if max_cost is not None and ((p.cost_per_1m_input * 0.75 + p.cost_per_1m_output * 0.25) / 1_000_000) > max_cost: continue
            capability_bonus=1.0 if task_type in p.capabilities else 0.0
            if priority=='quality': score=p.quality_score*2 + p.latency_score*.25 + capability_bonus
            elif priority=='latency': score=p.latency_score*2 + p.quality_score*.25 + capability_bonus
            elif priority=='cost':
                expected_cost_per_million = p.cost_per_1m_input * 0.75 + p.cost_per_1m_output * 0.25
                score=(1/(1+expected_cost_per_million))*3 + p.quality_score*.1 + capability_bonus
            else: score=p.quality_score + p.latency_score + capability_bonus
            candidates.append((score,p))
        if not candidates: raise RuntimeError('NO_HEALTHY_MODEL_AVAILABLE')
        return sorted(candidates,key=lambda x:x[0],reverse=True)
    def choose(self, task_type='general', priority='balanced', max_cost=None, required_capabilities=None):
        score,p=self.rank(task_type,priority,max_cost,required_capabilities)[0]
        return RouteDecision(p.provider,p.model,f'priority={priority};task={task_type}',score)

class RedisProviderHealth:
    """Shared provider circuit state for multiple gateway workers."""
    def __init__(self, redis_url, failure_threshold=3, recovery_seconds=30):
        import redis
        self.client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.prefix = "gateway:provider-health:"

    def _key(self, key, suffix):
        return f"{self.prefix}{key}:{suffix}"

    def record_success(self, key, latency_ms):
        pipe = self.client.pipeline(transaction=True)
        pipe.delete(self._key(key, "failures"), self._key(key, "open"))
        pipe.set(self._key(key, "latency_ms"), float(latency_ms), ex=86400)
        pipe.execute()

    def record_failure(self, key):
        pipe = self.client.pipeline(transaction=True)
        pipe.incr(self._key(key, "failures"))
        pipe.expire(self._key(key, "failures"), max(self.recovery_seconds * 4, 60))
        count, _ = pipe.execute()
        if int(count) >= self.failure_threshold:
            self.client.set(self._key(key, "open"), "1", ex=self.recovery_seconds)

    def available(self, key):
        if self.client.exists(self._key(key, "open")):
            return False
        return True

    def snapshot(self):
        result = {}
        for key in self.client.scan_iter(match=f"{self.prefix}*:failures"):
            base = key[:-len(":failures")]
            name = base[len(self.prefix):]
            result[name] = {"failures": int(self.client.get(key) or 0),
                            "opened_at": bool(self.client.exists(base + ":open")),
                            "latency_ms": float(self.client.get(base + ":latency_ms") or 0)}
        return result


def build_provider_health(settings):
    if settings.app_env.lower() in {"prod", "production"} or settings.rate_limiter_backend.lower() == "redis":
        return RedisProviderHealth(settings.redis_url, settings.circuit_failure_threshold, settings.circuit_recovery_seconds)
    return ProviderHealth(settings.circuit_failure_threshold, settings.circuit_recovery_seconds)
