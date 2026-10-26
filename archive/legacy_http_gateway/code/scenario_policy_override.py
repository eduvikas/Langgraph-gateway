"""
Scenario: policy override.

A contract summarizer request is complex enough to normally route to the
frontier tier — but it's flagged data-sensitive (say, it contains a
client's PII or a regulated data class). Step 3 of the routing pipeline
(see the architecture diagram) catches that flag and forces the small,
self-hosted tier regardless of complexity: the request never reaches an
external API.

Run: python scenario_policy_override.py
"""
from gateway_graph import AIGateway, APPS

APP_ID = "contracts"
PROMPT = "Summarize this vendor contract, including the named client's account and billing details."


def main():
    gateway = AIGateway()
    app_name = APPS[APP_ID]["name"]

    print(f"Same request, sent twice from: {app_name}\n")

    print("Without the data-sensitive flag:")
    r1 = gateway.process(APP_ID, PROMPT, force_complexity="complex")
    print(f"  tier={r1['tier']:<10} policy_override={r1['policy_override']}  cost=${r1['cost']:.4f}")

    print("\nWith the data-sensitive flag set (PII detected upstream):")
    r2 = gateway.process(APP_ID, PROMPT + " (case 2)", force_complexity="complex", data_sensitive=True)
    print(f"  tier={r2['tier']:<10} policy_override={r2['policy_override']}  cost=${r2['cost']:.4f}")

    print(
        "\nSame complexity, same app — the second request never reached the "
        "frontier API. The policy check in classify() overrode the routing "
        "score and forced it onto self-hosted compute."
    )


if __name__ == "__main__":
    main()
