"""Exact-match response cache.

An identical request gets the stored answer for free instead of a second model call. It is built to
be safe to share, because one application's users all read from the same cache:

* governance (identity, roles, rate limits, security rules) runs BEFORE the cache, so a cached answer
  never bypasses an access decision;
* the key includes the application, the routed model, the prompt and the whole conversation history,
  so different apps, models and conversations never share an entry;
* only `public` and `internal` requests are cached. Anything classified confidential or restricted, or
  containing PII or secrets, is never stored or served from the cache;
* an application can opt out (`allow_cache: false` in its policy);
* only answers that passed evaluation are stored, and entries expire after CACHE_TTL_SECONDS;
* a cache failure is treated as a miss and never fails the request.

It matches only exact (whitespace-trimmed) prompts. Semantic matching would raise the hit rate but
brings a real risk of serving a wrong answer, so it is deliberately not done here.
"""
import hashlib
import json
import logging
import time
from collections import OrderedDict
from threading import RLock

logger = logging.getLogger(__name__)
CACHEABLE_CLASSIFICATIONS = {"public", "internal"}


def make_cache_key(application_id, model, prompt, history):
    payload = json.dumps([application_id, model, prompt.strip(), [[h.get("role"), h.get("content")] for h in history]],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def skip_reason(policy, state):
    """None if this request may use the cache, otherwise why not."""
    if not policy.allow_cache:
        return "disabled_by_policy"
    if state.get("data_classification", "internal") not in CACHEABLE_CLASSIFICATIONS:
        return "sensitive_classification"
    if any(f.get("category") in ("PII", "SECRET") for f in state.get("security_findings", [])):
        return "sensitive_content"
    return None


class InMemoryResponseCache:
    """Process-local LRU with a TTL. Fine for one instance; use Redis to share across instances."""
    def __init__(self, ttl_seconds=3600, max_entries=1000, clock=time.time):
        self.ttl, self.max_entries, self.clock = ttl_seconds, max_entries, clock
        self._items, self._lock = OrderedDict(), RLock()

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item is None: return None
            expires_at, entry = item
            if expires_at <= self.clock():
                del self._items[key]; return None
            self._items.move_to_end(key)
            return entry

    def set(self, key, entry):
        with self._lock:
            self._items[key] = (self.clock() + self.ttl, entry)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class RedisResponseCache:
    def __init__(self, client, ttl_seconds=3600, prefix="gateway:response:"):
        self.client, self.ttl, self.prefix = client, ttl_seconds, prefix

    def get(self, key):
        try:
            raw = self.client.get(self.prefix + key)
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001 - a cache outage must not fail requests
            logger.warning("response cache read failed; treating as a miss", exc_info=True)
            return None

    def set(self, key, entry):
        try:
            self.client.setex(self.prefix + key, self.ttl, json.dumps(entry))
        except Exception:  # noqa: BLE001
            logger.warning("response cache write failed", exc_info=True)


def build_response_cache(settings):
    if not settings.cache_enabled:
        return None
    if settings.cache_backend == "redis" and settings.redis_url:
        import redis
        return RedisResponseCache(redis.from_url(settings.redis_url, decode_responses=True), settings.cache_ttl_seconds)
    return InMemoryResponseCache(settings.cache_ttl_seconds, settings.cache_max_entries)
