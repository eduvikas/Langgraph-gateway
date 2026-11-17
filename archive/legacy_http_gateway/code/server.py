"""
AI Gateway service — an OpenAI-compatible HTTP layer over the routing,
caching, and budget logic used elsewhere in this project.

Point any OpenAI-compatible client at this (base_url + api_key are the
only two things that change) and every call gets classified, routed to a
tier, checked against cache, checked against an app AND a per-run budget,
and either served or rejected — same ideas as gateway_graph.py's
AIGateway, wired up as a real service instead of an in-process demo.

Caching, budget enforcement, and observability are implemented as
decorator-based aspects (aspects.py) around _invoke(), the one function
that actually calls a model — rather than inlined into this endpoint.
See aspects.py's module docstring for why the streaming path below calls
the same aspect logic as plain functions instead of through the
decorators directly.

Run:
    uvicorn server:app --reload --port 8000

See README_SERVICE.md for the full request/response contract, the header
list, and how to point a real agent (LangChain, the openai SDK, anything
OpenAI-compatible) at it.
"""
import asyncio
import json
import queue
import threading
import time
import uuid

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from aspects import (
    CallContext, check_cache, finalize_cost, reserve_budget,
    with_budget, with_cache, with_observability,
)
from classifier import TIER_ORDER, PolicyConflict, decide_tier, estimate_tokens
from errors import openai_error
from gateway_graph import APPS, MODEL_PRICING, MODELS, PROJECT_NAME
from model_backends import PROVIDER, REAL_MODELS_ENABLED
from schemas import (
    ChatCompletionRequest, ChatCompletionResponse, Choice, ChoiceMessage,
    ModelInfo, ModelList, Usage,
)
from state_store import store

app = FastAPI(title=f"{PROJECT_NAME} service", version="0.1.0")

DEFAULT_APP_BUDGET = 20.0
app_budget_overrides: dict[str, float] = {}


def get_app_budget(app_id: str) -> float:
    if app_id in app_budget_overrides:
        return app_budget_overrides[app_id]
    if app_id in APPS:
        return APPS[app_id]["daily_budget"]
    return DEFAULT_APP_BUDGET


def to_lc_messages(messages: list) -> list:
    lc = []
    for m in messages:
        content = m.content or ""
        if m.role == "system":
            lc.append(SystemMessage(content=content))
        elif m.role == "assistant":
            lc.append(AIMessage(content=content))
        else:  # user or tool — tool role folded into human for this simple path
            lc.append(HumanMessage(content=content))
    return lc


def lc_config(app_id, agent, run_id, step, parent_trace_id):
    tags = [app_id, "ai-gateway-service"]
    if agent:
        tags.append(agent)
    metadata = {"app_id": app_id, "run_id": run_id, "step": step}
    if parent_trace_id:
        # Best-effort nesting: full distributed tracing requires the
        # calling app's own LangSmith SDK to propagate a real parent run
        # id, not just a header we relay into metadata.
        metadata["parent_trace_id"] = parent_trace_id
    return {"run_name": f"{PROJECT_NAME}::{app_id}", "tags": tags, "metadata": metadata}


def build_headers(ctx: CallContext, decision, run_id: str) -> dict:
    return {
        "X-AI-Gateway-Tier": ctx.tier,
        "X-AI-Gateway-Cache": "hit" if ctx.cache_hit else "miss",
        "X-AI-Gateway-Complexity-Score": str(decision.complexity_score),
        "X-AI-Gateway-Policy-Override": str(decision.policy_override).lower(),
        "X-AI-Gateway-Capability-Override": str(decision.capability_override).lower(),
        "X-AI-Gateway-Run-Id": run_id,
        "X-AI-Gateway-Backend": "real" if REAL_MODELS_ENABLED else "mock",
        # HTTP header values must be Latin-1: defensively strip anything
        # outside that range (an em dash, a curly quote) rather than 500
        # on it the next time someone edits a reason string.
        "X-AI-Gateway-Reasons": " | ".join(decision.reasons).encode("latin-1", "replace").decode("latin-1"),
    }


def sse_chunk(id_, model_name, delta: dict, finish_reason=None):
    payload = {
        "id": id_, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def sse_usage_chunk(id_, model_name, prompt_tokens, completion_tokens):
    payload = {
        "id": id_, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model_name, "choices": [],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                   "total_tokens": prompt_tokens + completion_tokens},
    }
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# The core call — three aspects stacked around it. Read bottom-up: with_budget
# is innermost (closest to the real work), with_cache wraps that (so a cache
# hit skips the budget check too), with_observability wraps everything (logs
# every path, including blocked and cached ones).
# ---------------------------------------------------------------------------
@with_observability
@with_cache
@with_budget
async def _invoke(ctx: CallContext, model, lc_messages, config) -> CallContext:
    """The actual model call — the one piece of real work the aspects
    above wrap. No caching or budget logic lives here anymore; just
    'call the model, work out what it cost.'"""
    result = await asyncio.to_thread(model.invoke, lc_messages, config=config)
    usage_meta = getattr(result, "usage_metadata", None)
    if usage_meta and usage_meta.get("total_tokens"):
        prompt_tokens = usage_meta.get("input_tokens", ctx.token_estimate)
        completion_tokens = usage_meta.get("output_tokens", 0)
        total_tokens = usage_meta["total_tokens"]
    else:
        prompt_tokens = ctx.token_estimate
        completion_tokens = max(1, len(result.content) // 4)
        total_tokens = prompt_tokens + completion_tokens

    ctx.actual_cost = (total_tokens / 1_000_000) * MODEL_PRICING[ctx.tier]["price_per_m_tokens"]
    ctx.result_content = result.content
    ctx.usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}
    return ctx


async def stream_model(model, lc_messages, config, id_, model_name, ctx: CallContext):
    """Bridges langchain's synchronous .stream() into an async SSE generator
    via a background thread + queue, then calls the same finalize_cost
    aspect function _invoke uses, once the stream (and therefore real
    token usage) is actually known."""
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            for chunk in model.stream(lc_messages, config=config):
                q.put(chunk)
        except Exception as e:  # noqa: BLE001 — surfaced to the client below
            q.put(e)
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    yield sse_chunk(id_, model_name, {"role": "assistant"})
    full_text = ""
    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is None:
            break
        if isinstance(item, Exception):
            yield sse_chunk(id_, model_name, {"content": f"[stream error: {item}]"}, finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        piece = item.content or ""
        if piece:
            full_text += piece
            yield sse_chunk(id_, model_name, {"content": piece})

    yield sse_chunk(id_, model_name, {}, finish_reason="stop")
    completion_tokens = max(1, len(full_text) // 4)
    yield sse_usage_chunk(id_, model_name, ctx.token_estimate, completion_tokens)
    yield "data: [DONE]\n\n"

    total_tokens = ctx.token_estimate + completion_tokens
    ctx.actual_cost = (total_tokens / 1_000_000) * MODEL_PRICING[ctx.tier]["price_per_m_tokens"]
    finalize_cost(ctx)  # same aspect function _invoke's with_budget decorator uses
    store.app_add_outcome(ctx.app_id)


async def stream_cached(text, id_, model_name, app_id):
    yield sse_chunk(id_, model_name, {"role": "assistant"})
    yield sse_chunk(id_, model_name, {"content": text})
    yield sse_chunk(id_, model_name, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"
    store.app_add_outcome(app_id)


@app.get("/health")
async def health():
    return {"status": "ok", "backend": "real" if REAL_MODELS_ENABLED else "mock",
            "provider": PROVIDER if REAL_MODELS_ENABLED else None}


@app.get("/v1/models")
async def list_models():
    ids = ["ai-gateway/auto", "ai-gateway/small", "ai-gateway/mid", "ai-gateway/frontier"]
    return ModelList(data=[ModelInfo(id=i) for i in ids])


@app.get("/v1/admin/policy")
async def get_policy():
    """Read-only view of the current routing policy. Making these
    thresholds live-editable (rather than constants in classifier.py) is
    the natural next step — see README_SERVICE.md."""
    return {
        "tier_thresholds": {"small": "< 0.30", "mid": "0.30 - 0.70", "frontier": "> 0.70"},
        "tier_pricing_per_m_tokens": {t: MODEL_PRICING[t]["price_per_m_tokens"] for t in MODEL_PRICING},
        "tier_infra": {t: MODEL_PRICING[t]["infra"] for t in MODEL_PRICING},
        "default_app_daily_budget": DEFAULT_APP_BUDGET,
        "app_budget_overrides": app_budget_overrides,
        "backend": "real" if REAL_MODELS_ENABLED else "mock",
    }


@app.patch("/v1/admin/apps/{app_id}")
async def set_app_budget(app_id: str, daily_budget: float):
    app_budget_overrides[app_id] = daily_budget
    return {"app_id": app_id, "daily_budget": daily_budget}


@app.get("/v1/outcomes")
async def outcomes():
    app_ids = set(store.app_spend) | set(store.app_outcomes) | set(store.app_baseline)
    rows = []
    for app_id in sorted(app_ids):
        spend = store.app_spend_get(app_id)
        baseline = store.app_baseline.get(app_id, 0.0)
        n = store.app_outcomes.get(app_id, 0)
        rows.append({
            "app_id": app_id,
            "outcomes_delivered": n,
            "spend": round(spend, 6),
            "baseline_spend": round(baseline, 6),
            "cost_per_outcome": round(spend / n, 6) if n else 0.0,
            "baseline_cost_per_outcome": round(baseline / n, 6) if n else 0.0,
            "blocked": store.app_blocked.get(app_id, 0),
        })
    return {"requests": store.requests, "cache_hits": store.cache_hits,
            "tier_counts": store.tier_counts, "apps": rows}


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    x_app_id: str | None = Header(None, alias="X-App-Id"),
    x_agent: str | None = Header(None, alias="X-Agent"),
    x_run_id: str | None = Header(None, alias="X-Run-Id"),
    x_step: int | None = Header(None, alias="X-Step"),
    x_sensitivity: str | None = Header(None, alias="X-Sensitivity"),
    x_min_tier: str | None = Header(None, alias="X-Min-Tier"),
    x_max_tier: str | None = Header(None, alias="X-Max-Tier"),
    x_run_max_budget: float | None = Header(None, alias="X-Run-Max-Budget"),
    x_run_max_steps: int | None = Header(None, alias="X-Run-Max-Steps"),
    x_parent_trace_id: str | None = Header(None, alias="X-Parent-Trace-Id"),
):
    meta = req.metadata or {}
    app_id = x_app_id or meta.get("app_id") or "default"
    agent = x_agent or meta.get("agent")
    run_id = x_run_id or meta.get("run_id") or str(uuid.uuid4())
    step = x_step if x_step is not None else int(meta.get("step", 0))

    sensitive_raw = x_sensitivity if x_sensitivity is not None else meta.get("data_sensitive")
    data_sensitive = str(sensitive_raw).lower() in ("1", "true", "yes", "y") if sensitive_raw is not None else False
    min_tier = x_min_tier or meta.get("min_tier")
    max_tier = x_max_tier or meta.get("max_tier")
    run_max_budget = x_run_max_budget if x_run_max_budget is not None else meta.get("run_max_budget")
    run_max_steps = x_run_max_steps if x_run_max_steps is not None else meta.get("run_max_steps")

    explicit_tier = None
    if req.model.startswith("ai-gateway/") and req.model != "ai-gateway/auto":
        candidate = req.model.split("/", 1)[1]
        if candidate in TIER_ORDER:
            explicit_tier = candidate

    has_tools = bool(req.tools)
    text_parts = [m.content for m in req.messages]

    try:
        decision = decide_tier(
            text_parts, has_tools=has_tools, step=step, data_sensitive=data_sensitive,
            explicit_tier=explicit_tier, min_tier=min_tier, max_tier=max_tier,
        )
    except PolicyConflict as e:
        raise openai_error(403, str(e), "policy_conflict", code="ai_gateway_policy_conflict")

    tier = decision.tier
    store.get_run(run_id, max_budget=run_max_budget, max_steps=run_max_steps)

    cacheable = (not has_tools) and (req.temperature is not None and req.temperature <= 0.05)
    messages_dict = [m.model_dump() for m in req.messages]
    tools_dict = [t.model_dump() for t in req.tools] if req.tools else None
    cache_key = store.cache_key(app_id, messages_dict, tools_dict)

    token_estimate = estimate_tokens(text_parts)
    est_cost = (token_estimate / 1_000_000) * MODEL_PRICING[tier]["price_per_m_tokens"]
    baseline_cost = (token_estimate / 1_000_000) * MODEL_PRICING["frontier"]["price_per_m_tokens"]
    store.app_add_baseline(app_id, baseline_cost)

    ctx = CallContext(
        app_id=app_id, run_id=run_id, tier=tier, cacheable=cacheable, cache_key=cache_key,
        est_cost=est_cost, app_budget=get_app_budget(app_id), token_estimate=token_estimate,
    )

    id_ = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    model = MODELS[tier]
    if has_tools and REAL_MODELS_ENABLED and PROVIDER == "openai":
        model = model.bind_tools([t["function"] for t in tools_dict])
    lc_messages = to_lc_messages(req.messages)
    config = lc_config(app_id, agent, run_id, step, x_parent_trace_id)

    if req.stream:
        # Can't use the @with_cache/@with_budget decorators on a generator
        # (see aspects.py) — call the same underlying functions directly,
        # at the equivalent "before" point in the flow.
        if not check_cache(ctx):
            blocked = reserve_budget(ctx)
            if blocked:
                store.app_add_blocked(app_id)
                raise openai_error(429, blocked, "budget_exceeded",
                                    code="ai_gateway_budget_exceeded")

        store.record_request(cache_hit=ctx.cache_hit)
        headers = build_headers(ctx, decision, run_id)

        if ctx.cache_hit:
            return StreamingResponse(stream_cached(ctx.result_content, id_, req.model, app_id),
                                      media_type="text/event-stream", headers=headers)
        return StreamingResponse(
            stream_model(model, lc_messages, config, id_, req.model, ctx),
            media_type="text/event-stream", headers=headers,
        )

    # Non-streaming: the three aspects handle cache + budget + the call.
    ctx = await _invoke(ctx, model, lc_messages, config)

    if ctx.blocked_reason:
        store.app_add_blocked(app_id)
        raise openai_error(429, ctx.blocked_reason, "budget_exceeded",
                            code="ai_gateway_budget_exceeded")

    store.record_request(cache_hit=ctx.cache_hit)
    store.app_add_outcome(app_id)

    headers = build_headers(ctx, decision, run_id)
    headers["X-AI-Gateway-Cost"] = f"{ctx.actual_cost:.6f}"
    if not ctx.cache_hit:
        headers["X-AI-Gateway-Run-Spend"] = f"{store.get_run(run_id).spend:.6f}"

    resp = ChatCompletionResponse(
        id=id_, created=int(time.time()), model=req.model,
        choices=[Choice(message=ChoiceMessage(content=ctx.result_content))],
        usage=Usage(**ctx.usage),
    )
    return JSONResponse(content=resp.model_dump(), headers=headers)
