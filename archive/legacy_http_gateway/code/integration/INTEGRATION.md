# Integrating a real application with ai-gateway

Two files do all the work. Copy `gateway_client.py` into your application; read
`example_langgraph_app.py` for a complete multi-agent example (planner, researcher with a
tool, reviewer with sensitive data). Both were run against the live service.

## 1. Configure

    export AI_GATEWAY_URL=https://ai-gateway.internal/v1
    export AI_GATEWAY_KEY=<this app's virtual key>
    export AI_GATEWAY_APP_ID=claims

## 2. Replace each agent's model client

Before:

    llm = ChatOpenAI(model="gpt-4o")

After:

    from gateway_client import make_llm, invoke_guarded, new_run_id
    run_id = new_run_id()                          # one per agent run
    llm = make_llm("planner", run_id, step=1)      # model defaults to ai-gateway/auto
    msg, routing = invoke_guarded(llm, "your prompt")

`routing` holds tier, cost, cache, policy-override and capability-override for logging.

## 3. What changes for the application

| Change | Why |
|---|---|
| Use `ai-gateway/auto` instead of a fixed model | lets the router choose the tier |
| Reuse one `run_id` for every step of a run | the per-run budget and step cap are keyed on it |
| Pass `sensitive=True` from your PII / data-classification check | forces self-hosted compute |
| Catch `GatewayBlocked` (429) and `PolicyBlocked` (403) | stop or degrade the run; never retry |
| Re-run each agent's quality evals | routing changes which model answers |

`run_max_budget` and `run_max_steps` are fixed by a run's first call; later values are ignored.

## 4. Behavior worth knowing

- **Tools** attached with `bind_tools` bump a small-tier request to mid.
- **Sensitive** requests are forced to the small tier regardless of size. Sensitive plus
  `min_tier` above small is rejected with 403.
- **Caching** applies to calls with no tools and temperature <= 0.05. A cache hit is free and
  does not count against the run's budget or step cap. Identical prompts therefore skip the caps.
- **Retries:** budget and policy errors carry `x-should-retry: false`. Without it the OpenAI SDK
  retries 429s by default and a blocked agent freezes for about two minutes (measured: 120 s,
  now 0 s). Transient 5xx errors still retry normally.

## 5. Other clients

Plain OpenAI SDK:

    client = OpenAI(base_url=URL, api_key=KEY)
    client.chat.completions.create(model="ai-gateway/auto", messages=[...],
        extra_headers={"X-App-Id": "claims", "X-Run-Id": run_id, "X-Step": "1"})

Any language, plain HTTP:

    curl $AI_GATEWAY_URL/chat/completions -H "Authorization: Bearer $AI_GATEWAY_KEY" \
      -H "X-App-Id: claims" -H "X-Run-Id: run-1" -H "Content-Type: application/json" \
      -d '{"model":"ai-gateway/auto","messages":[{"role":"user","content":"hi"}]}'

Clients that cannot set headers can send the same fields in the body's `metadata` object.

## 4b. Expected output of the example

    agent       tier    cost        capability_override   policy_override
    planner     small   $0.000004   false                 false
    researcher  mid     $0.000060   true                  false
    reviewer    small   $0.000321   false                 true

With `--limit 2` the run stops after the researcher: "step limit (2) exceeded".

## 6. Before real traffic

This is verified against the mock backend only. Real OpenAI or Claude calls and live LangSmith
tracing have not been run from here. The production gaps (Redis state, real auth, a validated
classifier, streaming token counts) are listed in `../README_SERVICE.md`.
