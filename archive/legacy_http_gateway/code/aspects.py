"""
AOP-style aspects for the AI Gateway service: caching, budget enforcement,
and observability, pulled out of the core "call a model" logic so they
can be composed with decorators instead of inlined into the endpoint.

Python has no dedicated AOP framework in the language itself (unlike
AspectJ for Java); decorators are the idiomatic way to get the same
effect — wrap a function with "before"/"after" behavior without touching
its body. Each decorator below is one aspect; the "pointcut" is simply
wherever you apply the decorator — here, that's _invoke() in server.py,
the one function that actually calls a model.

Each decorator is a thin wrapper around a small plain function
(check_cache, reserve_budget, finalize_cost) that does the real work.
That split matters for one reason: the streaming path in server.py can't
use the decorators directly — a decorator that wraps a function returning
a single CallContext doesn't compose with a generator that yields many
SSE chunks over time, where "before the call" and "after the call" are
far apart and separated by a lot of other code. So streaming calls these
same plain functions directly, at the right points in its generator.
Same logic either way; just two different calling shapes for a
request/response function versus a long-lived generator.
"""
import functools
import time
from dataclasses import dataclass, field

from state_store import store


@dataclass
class CallContext:
    """Carries everything an aspect might read or write, so the decorators
    below don't need a growing list of positional arguments in common."""
    app_id: str
    run_id: str
    tier: str
    cacheable: bool
    cache_key: str | None
    est_cost: float
    app_budget: float
    token_estimate: int = 0

    cache_hit: bool = False
    blocked_reason: str | None = None
    result_content: str | None = None
    usage: dict = field(default_factory=dict)
    actual_cost: float = 0.0
    timings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plain functions — the actual work. The decorators further down are just
# these, applied automatically around a core function.
# ---------------------------------------------------------------------------
def check_cache(ctx: CallContext) -> bool:
    """Populates ctx from the cache and returns True on a hit. Whoever
    calls this is responsible for skipping everything downstream (budget
    check, model call) when it returns True — that's what makes a cache
    hit free, in dollars and in guardrail bookkeeping both."""
    if not ctx.cacheable:
        return False
    cached = store.cache_get(ctx.cache_key)
    if cached is None:
        return False
    ctx.cache_hit = True
    ctx.result_content = cached["content"]
    ctx.usage = cached["usage"]
    ctx.actual_cost = 0.0
    return True


def store_cache_if_applicable(ctx: CallContext):
    if ctx.cacheable and not ctx.blocked_reason and not ctx.cache_hit:
        store.cache_set(ctx.cache_key, {"content": ctx.result_content, "usage": ctx.usage})


def reserve_budget(ctx: CallContext) -> str | None:
    """Reserves ctx.est_cost against both the app's daily budget and the
    run's budget/step count. Returns a human-readable block reason, or
    None if the reservation succeeded. This is the one place either
    budget is actually checked — the with_budget decorator and the
    streaming path both call this, so there's exactly one implementation
    of the check to keep correct."""
    if store.app_spend_get(ctx.app_id) + ctx.est_cost > ctx.app_budget:
        return f"app '{ctx.app_id}' daily budget of {ctx.app_budget} exceeded"
    if not store.run_reserve(ctx.run_id, ctx.est_cost):
        run = store.get_run(ctx.run_id)
        return f"run '{ctx.run_id}' budget ({run.max_budget}) or step limit ({run.max_steps}) exceeded"
    return None


def finalize_cost(ctx: CallContext):
    """True up the pre-call reservation to the real cost, once it's known."""
    store.run_adjust_spend(ctx.run_id, ctx.actual_cost - ctx.est_cost)
    store.app_add_spend(ctx.app_id, ctx.actual_cost)
    store.record_tier(ctx.tier)


# ---------------------------------------------------------------------------
# The aspects — decorators around a core async function that takes a
# CallContext (plus whatever else it needs) and returns one, having set
# result_content / usage / actual_cost, or blocked_reason, on it.
# ---------------------------------------------------------------------------
def with_cache(func):
    """Aspect: short-circuits func entirely on a cache hit. This needs to
    be the outermost decorator — a cache hit should skip the budget check
    too, the same way a free answer should never count against anyone's
    budget."""
    @functools.wraps(func)
    async def wrapper(ctx: CallContext, *args, **kwargs):
        if check_cache(ctx):
            return ctx
        ctx = await func(ctx, *args, **kwargs)
        store_cache_if_applicable(ctx)
        return ctx
    return wrapper


def with_budget(func):
    """Aspect: reserves estimated cost before calling func; trues it up to
    the real cost after. Doesn't call func at all if the reservation is
    refused — ctx.blocked_reason carries why, for the caller to turn into
    a 429."""
    @functools.wraps(func)
    async def wrapper(ctx: CallContext, *args, **kwargs):
        blocked = reserve_budget(ctx)
        if blocked:
            ctx.blocked_reason = blocked
            return ctx
        ctx = await func(ctx, *args, **kwargs)
        if not ctx.blocked_reason:
            finalize_cost(ctx)
        return ctx
    return wrapper


def with_observability(func):
    """Aspect: one structured log line per call, independent of whichever
    path (cache hit, blocked, real call) was actually taken. This is the
    cross-cutting concern AOP was invented for — logging that would
    otherwise get copy-pasted into every branch."""
    @functools.wraps(func)
    async def wrapper(ctx: CallContext, *args, **kwargs):
        start = time.perf_counter()
        ctx = await func(ctx, *args, **kwargs)
        ctx.timings["seconds"] = round(time.perf_counter() - start, 4)
        print(
            f"[ai-gateway] app={ctx.app_id} run={ctx.run_id} tier={ctx.tier} "
            f"cache={'hit' if ctx.cache_hit else 'miss'} "
            f"blocked={bool(ctx.blocked_reason)} cost=${ctx.actual_cost:.6f} "
            f"took={ctx.timings['seconds']}s"
        )
        return ctx
    return wrapper
