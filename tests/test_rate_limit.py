from app.limits.rate_limiter import InMemoryRateLimiter
def test_rate_limit():
    r=InMemoryRateLimiter(2,60); assert r.allow("u")[0]; assert r.allow("u")[0]; assert not r.allow("u")[0]
