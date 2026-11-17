"""
A LangGraph multi-agent application wired to the ai-gateway service.

Three agents run in sequence for one claims case:
  planner     - plain reasoning
  researcher  - attaches a tool, so the gateway routes it off the small tier
  reviewer    - handles the claimant's personal data, so it is flagged sensitive
                and the gateway forces it onto self-hosted compute

Everything the application needed to change is in gateway_client.py's
make_llm() and invoke_guarded(). The graph itself is ordinary LangGraph.

Run the service first (cd .. && uvicorn server:app --port 8000), then:
    python example_langgraph_app.py            # normal run
    python example_langgraph_app.py --limit 2  # cap the run at 2 steps to see a block handled
"""
import argparse
from typing import TypedDict

from langgraph.graph import END, StateGraph

from gateway_client import GatewayBlocked, PolicyBlocked, invoke_guarded, make_llm, new_run_id

# Stand-in for a real claim attachment (large enough to matter for routing).
CLAIM_FILE = "Claimant statement, policy schedule and adjuster notes. " * 150

LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_coverage",
        "description": "Look up coverage limits for a policy number.",
        "parameters": {"type": "object", "properties": {"policy_no": {"type": "string"}}},
    },
}


class CaseState(TypedDict, total=False):
    run_id: str
    run_max_steps: int | None
    case: str
    plan: str
    findings: str
    verdict: str
    status: str            # "ok" or "blocked: ..."
    log: list              # one routing record per step


def run_step(state: CaseState, agent: str, step: int, prompt: str, *, tools=None, sensitive=False):
    """Call one agent through the gateway. Returns (text_or_None, state_update)."""
    llm = make_llm(agent, state["run_id"], step, sensitive=sensitive,
                   run_max_steps=state.get("run_max_steps"))
    if tools:
        llm = llm.bind_tools(tools)
    try:
        msg, routing = invoke_guarded(llm, prompt)
    except (GatewayBlocked, PolicyBlocked) as e:
        return None, {"status": f"blocked: {e}"}
    record = {"agent": agent, "tier": routing.get("tier"), "cost": routing.get("cost"),
              "policy_override": routing.get("policy-override"),
              "capability_override": routing.get("capability-override")}
    return msg.content, {"log": state.get("log", []) + [record], "status": "ok"}


def planner(state: CaseState):
    text, update = run_step(state, "planner", 1, f"Outline how to handle this claim: {state['case']}")
    return {**update, "plan": text} if text else update


def researcher(state: CaseState):
    text, update = run_step(state, "researcher", 2, f"Using the plan, look up coverage. Plan: {state['plan']}",
                            tools=[LOOKUP_TOOL])
    return {**update, "findings": text} if text else update


def reviewer(state: CaseState):
    prompt = (f"Review the findings against the claim file.\nClaim: {state['case']}\n"
              f"Findings: {state['findings']}\nFile: {CLAIM_FILE}")
    text, update = run_step(state, "reviewer", 3, prompt, sensitive=True)
    return {**update, "verdict": text} if text else update


def continue_or_stop(state: CaseState):
    return "stop" if state.get("status", "ok") != "ok" else "go"


def build_graph():
    g = StateGraph(CaseState)
    g.add_node("planner", planner)
    g.add_node("researcher", researcher)
    g.add_node("reviewer", reviewer)
    g.set_entry_point("planner")
    g.add_conditional_edges("planner", continue_or_stop, {"go": "researcher", "stop": END})
    g.add_conditional_edges("researcher", continue_or_stop, {"go": "reviewer", "stop": END})
    g.add_edge("reviewer", END)
    return g.compile()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap this run at N steps")
    args = ap.parse_args()

    app = build_graph()
    run_id = new_run_id("claim")
    # Real cases carry a unique id, so prompts differ run to run. (Identical prompts at
    # temperature 0 are served from the gateway cache: free, and exempt from run caps.)
    result = app.invoke({"run_id": run_id, "run_max_steps": args.limit,
                         "case": f"Water damage to a kitchen, claim {run_id}", "log": []})

    print(f"run {result['run_id']}  status: {result.get('status')}\n")
    print(f"{'agent':<12}{'tier':<8}{'cost':<12}{'capability_override':<22}{'policy_override'}")
    for r in result["log"]:
        print(f"{r['agent']:<12}{r['tier']:<8}${float(r['cost']):<11.6f}{r['capability_override']:<22}{r['policy_override']}")
    if result.get("status") != "ok":
        print(f"\nThe run stopped cleanly: {result['status']}")


if __name__ == "__main__":
    main()
