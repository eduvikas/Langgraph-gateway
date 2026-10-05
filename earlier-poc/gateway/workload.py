"""Synthetic traffic for five dummy applications over one simulated day."""
import random
import string

from .config import APPS, RUNAWAY_RATE
from .core import Request

HOUR_WEIGHTS = [0.2, 0.15, 0.1, 0.1, 0.15, 0.3, 0.6, 1.0, 1.6, 2.0, 2.2, 2.1,
                1.8, 2.0, 2.2, 2.0, 1.6, 1.1, 0.8, 0.6, 0.5, 0.4, 0.3, 0.25]

CORPUS = {
    "support-copilot": {
        "easy": ["How do I reset my password", "Where can I find my latest invoice", "What are your support hours",
                 "How do I update my billing address", "Can I change my subscription plan",
                 "How do I turn on two factor authentication", "What is your refund policy",
                 "How do I cancel my order", "Where is my order tracking number", "How do I download the mobile app",
                 "Can I add another user to my account", "How do I change my display name",
                 "Why can't I see the invoices tab"],
        "medium": ["Explain why my invoice shows a duplicate charge", "Troubleshoot why my sync keeps failing after the update",
                   "Draft a polite reply to a customer asking for a refund after thirty days",
                   "Walk me through moving my data to a new workspace",
                   "Explain the difference between the team plan and the enterprise plan",
                   "Summarize this customer complaint and suggest next steps", "Why is my dashboard loading slowly",
                   "Draft an apology for a delayed shipment"],
        "hard": ["Analyze this escalation thread and propose a root cause and fix plan across billing and provisioning",
                 "Debug why webhook retries create duplicate records for enterprise tenants",
                 "Analyze recurring churn complaints and propose a multi-step retention plan",
                 "Investigate the intermittent login failures across regions",
                 "Synthesize feedback from these tickets into a prioritized product plan",
                 "Design a escalation policy for repeated outage tickets",
                 "Work out the cause of the intermittent login failures across regions"]},
    "code-review-bot": {
        "easy": ["Fix the typo in this variable name", "Add a docstring to this function", "Rename this method to snake case",
                 "Remove the unused import", "Add type hints to this function", "Format this function to the style guide"],
        "medium": ["Review this function and suggest cleaner error handling", "Explain what this function does and draft unit tests",
                   "Review this pull request for naming and style issues", "Draft a commit message and summary for this change",
                   "Explain why this test is flaky", "Review the error handling in this handler"],
        "hard": ["Analyze this diff for concurrency bugs and race conditions",
                 "Refactor this module to remove circular dependencies and explain the trade-off",
                 "Find the root cause of this memory leak and propose a fix",
                 "Review this change for security vulnerabilities in the authentication flow",
                 "Debug this intermittent deadlock in the worker pool",
                 "Analyze the performance regression introduced by this change",
                 "Figure out why this service returns stale data under load"]},
    "doc-summarizer": {
        "easy": ["Extract the effective date and parties from this agreement", "List the section headings of this document",
                 "Find the total contract value mentioned in this document", "Extract all deadlines from this document"],
        "medium": ["Summarize this document in five bullet points", "Summarize the key obligations and deadlines in this contract",
                   "Draft an executive summary of this policy document", "Explain the payment terms in this agreement",
                   "Summarize the changes between these two versions"],
        "hard": ["Analyze the indemnification clause and compare it with our standard clause",
                 "Synthesize risks across these three vendor agreements and forecast exposure",
                 "Identify conflicting clauses in this contract and propose a redline",
                 "Analyze the liability cap and explain the trade-off for renewal",
                 "Work out what this termination clause means for our renewal"]},
    "hr-faq-bot": {
        "easy": ["How many vacation days do I get", "What is the parental leave policy", "When is the next payroll date",
                 "How do I submit an expense report", "What are the office holiday dates", "How do I update my bank details",
                 "What is the remote work policy", "How do I request a new laptop", "Where can I find my payslip",
                 "What is the sick leave policy", "How do I enroll in health benefits", "What is the notice period policy",
                 "How do I book a meeting room", "Where is the employee handbook", "How do I change my emergency contact",
                 "What is the learning budget per year"],
        "medium": ["Explain how my unused leave carries over into next year", "Why was my last bonus payout lower than expected",
                   "Draft a request to my manager for flexible working hours", "Explain how overtime is calculated for my role",
                   "Walk me through the promotion process"],
        "hard": ["Compare the tax trade-off between two relocation packages and analyze the impact on my net pay"]},
    "research-agent": {
        "easy": ["Extract the key figures from this source", "List the sources cited in this passage",
                 "Extract company names mentioned in this article"],
        "medium": ["Summarize the findings from this source and explain relevance", "Compare the claims in these two reports",
                   "Draft an outline for the research brief"],
        "hard": ["Synthesize findings across sources and analyze market trends then forecast demand",
                 "Analyze competitor strategy and compare the trade-offs between entry options",
                 "Design a multi-step plan to validate this hypothesis",
                 "Analyze regulatory risk across regions and propose mitigation"]},
}

VOCAB = """invoice tenant region latency shipment warranty upgrade portal license checkout coupon device firmware
onboarding quota dashboard export webhook cluster payroll benefit contract renewal vendor audit archive template
network gateway token workspace billing refund address session profile report backup migration schema endpoint
queue cache index policy ticket channel account roadmap pricing supplier compliance approval quarter inventory""".split()
PREFIX = ["", "", "", "Hi, ", "Hello, ", "Please ", "Could you tell me: ", "Quick question - "]
SUFFIX = ["", "", "", " thanks", " please", "?"]
SNIPPET = "def process(items):\n    for i in items:\n        handle(i)\n"


def _hour_ts(rng):
    return rng.choices(range(24), weights=HOUR_WEIGHTS)[0] * 3600 + rng.uniform(0, 3600)


def _pii(app, rng):
    name = "".join(rng.choices(string.ascii_lowercase, k=6))
    if app == "hr-faq-bot":
        return f" My employee id is EMP{rng.randint(100000, 999999)} and my email is {name}@corp.example.com."
    if app == "support-copilot":
        return f" My email is {name}@example.com and my phone is +1 555 {rng.randint(100, 999)} {rng.randint(1000, 9999)}."
    if app == "doc-summarizer":
        return f" Contact: {name}@partner.example.com."
    key = "".join(rng.choices(string.ascii_uppercase + string.digits, k=16))
    return f'\nAWS_KEY = "AKIA{key}"'


def _make_prompt(app, cx, rng):
    pool = CORPUS[app.name]
    if rng.random() < app.repeat_rate:                       # recurring question, lightly paraphrased
        cx = rng.choices(["easy", "medium", "hard"], weights=app.mix)[0]
        items = pool[cx]
        base = rng.choices(items, weights=[1 / (i + 1) ** 1.1 for i in range(len(items))])[0]
        text = rng.choice(PREFIX) + (base[0].lower() + base[1:] if base[:1].isupper() and rng.random() < 0.5 else base) + rng.choice(SUFFIX)
        return cx, text
    base = rng.choice(pool[cx])                              # one-off question with unique details
    return cx, base + " regarding " + " ".join(rng.sample(VOCAB, 6))


def build_workload(seed=42, scale=1.0):
    rng, reqs, rid = random.Random(seed), [], 0
    for app in APPS.values():
        for n in range(int(app.volume * scale)):
            if not app.agentic:
                cx = rng.choices(["easy", "medium", "hard"], weights=app.mix)[0]
                cx, prompt = _make_prompt(app, cx, rng)
                pii = rng.random() < app.pii_rate
                if pii:
                    snippet_pii = _pii(app.name, rng)
                    prompt = prompt + snippet_pii if app.name != "code-review-bot" else prompt
                if app.name == "code-review-bot":
                    prompt = f"{prompt}\n```python\n{SNIPPET}{_pii(app.name, rng) if pii else ''}\n```"
                user = rng.randint(*app.user_tokens)
                out = int(rng.randint(*app.out_tokens) * {"easy": 0.7, "medium": 1.0, "hard": 1.3}[cx])
                rid += 1
                reqs.append(Request(rid, _hour_ts(rng), app.name, prompt, app.sys_tokens + user, out,
                                    app.sys_tokens, cx, has_pii=pii))
            else:                                            # one agent run = several chained calls
                t0, runaway = _hour_ts(rng), rng.random() < RUNAWAY_RATE
                calls, ctx, ts = (80 if runaway else rng.randint(3, 8)), 0, 0.0
                for i in range(calls):
                    cx = "hard" if runaway else rng.choices(["easy", "medium", "hard"], weights=app.mix)[0]
                    prompt = (f"Retry: analyze the source again and continue the plan, attempt {i}" if runaway
                              else rng.choice(CORPUS[app.name][cx]) + " regarding " + " ".join(rng.sample(VOCAB, 6)))
                    user = rng.randint(*app.user_tokens)
                    out = int(rng.randint(*app.out_tokens) * {"easy": 0.7, "medium": 1.0, "hard": 1.3}[cx])
                    ts += rng.uniform(2, 15)
                    rid += 1
                    reqs.append(Request(rid, t0 + ts, app.name, prompt, app.sys_tokens + user + ctx, out,
                                        app.sys_tokens, cx, run_id=f"{app.name}-{n}", wasted=runaway))
                    ctx = min(ctx + rng.randint(300, 900), 60_000)
    reqs.sort(key=lambda r: (r.ts, r.id))
    return reqs
