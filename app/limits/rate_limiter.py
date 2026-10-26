import time
from collections import defaultdict
from threading import RLock

class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self._data = defaultdict(list); self._lock = RLock()
    def allow(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            values = [x for x in self._data[key] if x > now - self.window]
            if len(values) >= self.limit:
                self._data[key] = values
                return False, 0
            values.append(now); self._data[key] = values
            return True, self.limit - len(values)

class RedisRateLimiter:
    def __init__(self, url: str, limit: int, window_seconds: int):
        import redis
        self.client = redis.from_url(url, decode_responses=True)
        self.limit, self.window = limit, window_seconds
    def allow(self, key: str) -> tuple[bool, int]:
        # Fixed-window counter: set expiry only on the first increment. The Lua script
        # makes increment + expiry atomic across gateway workers.
        bucket = f"gateway:ratelimit:{key}"
        script = "local n=redis.call('INCR', KEYS[1]); if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; return n"
        count = int(self.client.eval(script, 1, bucket, self.window))
        return count <= self.limit, max(0, self.limit - count)

def build_rate_limiter(settings):
    if settings.rate_limiter_backend.lower() == "redis":
        return RedisRateLimiter(settings.redis_url, settings.rate_limit_requests, settings.rate_limit_window_seconds)
    return InMemoryRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
