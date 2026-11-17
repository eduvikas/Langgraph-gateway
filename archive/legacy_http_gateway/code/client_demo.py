"""
Proof that a real agent can point at AI Gateway by changing only base_url
and api_key — nothing else about how it calls a model changes.

Uses the actual `openai` Python SDK (the same one LangChain's ChatOpenAI
uses under the hood), pointed at this local service instead of OpenAI's
API. Runs a small simulated multi-step agent loop for one claims-review
run: a few ordinary planning steps, one step that attaches a tool (proving
capability-aware routing), and one step flagged data-sensitive (proving
the policy override) — then keeps looping with a tiny run budget until
the gateway blocks it, so you can see the guardrail actually fire.

Run the server first:
    uvicorn server:app --port 8000
Then, in another terminal:
    python client_demo.py
"""
import uuid

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="ai-gateway-demo-key")

APP_ID = "claims"
RUN_ID = f"run-{uuid.uuid4().hex[:8]}"


def call(step: int, content: str, *, tools=None, sensitive: bool = False,
         run_max_budget: float | None = None, model: str = "ai-gateway/auto",
         run_id: str | None = None):
    headers = {
        "X-App-Id": APP_ID,
        "X-Agent": "claims-planner",
        "X-Run-Id": run_id or RUN_ID,
        "X-Step": str(step),
    }
    if sensitive:
        headers["X-Sensitivity"] = "true"
    if run_max_budget is not None:
        headers["X-Run-Max-Budget"] = str(run_max_budget)

    kwargs = {"model": model, "messages": [{"role": "user", "content": content}]}
    if tools:
        kwargs["tools"] = tools

    raw = client.chat.completions.with_raw_response.create(extra_headers=headers, **kwargs)
    h = raw.headers
    parsed = raw.parse()
    print(
        f"  step {step:<2} tier={h.get('x-ai-gateway-tier'):<9} "
        f"policy_override={h.get('x-ai-gateway-policy-override'):<5} "
        f"capability_override={h.get('x-ai-gateway-capability-override'):<5} "
        f"cost=${float(h.get('x-ai-gateway-cost', 0)):.6f}  "
        f"run_spend=${float(h.get('x-ai-gateway-run-spend', 0) or 0):.6f}"
    )
    return parsed


def main():
    print(f"Run: {RUN_ID}\n")

    print("Step 1 — ordinary planning step:")
    call(1, "Outline what's needed to process this claim.")

    print("\nStep 2 — needs a tool (capability-aware routing should bump the tier):")
    call(2, "Look up the policyholder's coverage limits.", tools=[
        {"type": "function", "function": {"name": "lookup_coverage", "parameters": {}}}
    ])

    print("\nStep 3 — a large request touching PII. Same payload twice: unflagged routes up on size;")
    print("         flagged, the policy override forces it down to the small, self-hosted tier:")
    pii_payload = "Cross-check the claimant's name and SSN against the policy record. " * 150
    call(3, pii_payload)
    call(3, pii_payload + " ", sensitive=True)

    print("\nSteps 4+ — long analysis loop on a tight run budget (a fresh run scope), until the guardrail fires:")
    loop_run_id = f"{RUN_ID}-loop"
    big_context = "Re-analyze the full claim history and supporting documents. " * 18
    for step in range(1, 40):
        try:
            call(step, big_context, run_max_budget=0.02, model="ai-gateway/frontier", run_id=loop_run_id)
        except Exception as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code == 429:
                message = resp.json()["detail"]["error"]["message"]
                print(f"  step {step:<2} -> BLOCKED (429): {message}")
                print("\nGuardrail engaged — the loop stopped instead of running up an open-ended bill.")
                break
            raise


if __name__ == "__main__":
    main()
