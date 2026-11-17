# Presenting the gateway to senior technical leadership

A 10-minute talk track built around the dashboard (`showcase/ai-gateway-showcase.html`), with the questions you are most likely to get and answers that stay inside what has been verified. Everything not yet verified is listed in [VERIFICATION.md](VERIFICATION.md); this guide tells you how to say so without weakening the pitch.

## Before the meeting

- Present from the **offline file** (double-click it), not the published link: no network dependency, and the reconcile panel works.
- If you have a real run, regenerate first ([SHOWCASE.md](SHOWCASE.md)) and confirm the badge says "Real OpenAI provider". If not, the badge says "Simulated model provider"; say so in your first sentence.
- Open it on the device you will present from and check the layout. It has never been viewed in a real browser by the author.
- Have two fallbacks ready: `demo/mcp-demo-replay.html` (terminal replay) and the architecture diagram.
- If you plan to show OpenAI's side, have the project's Spend limits screen open in a second tab. Hide your key.

## The 10-minute flow

| Min | Do | Say |
|---|---|---|
| 0:00 | Point at the badges | "Everything on this page comes from one real run of the gateway. The model provider is [simulated / OpenAI]; the gateway is real code." |
| 1:00 | Read **What to notice** | The four sentences are generated from the data: served vs stopped, which model served what, outage handled, every request recorded. |
| 2:00 | **Proof panel** | "The page recomputes its own totals from raw records. Every check is live; a failure would show a red ✗." This is your credibility moment. |
| 3:30 | **Spend** and **where requests went** | Cost against an all-premium baseline, and who used which tier. Call the saving "an illustration on scripted traffic" unless it is a measured live run. |
| 5:00 | **Stopped before reaching any model** | Shadow AI, injection, a pasted credential, personal data, a budget limit: five different controls, zero cost. |
| 6:30 | **Four layers keep spend bounded** | Be explicit that layer 1 is OpenAI's, not the gateway's. "The gateway's budget is an estimate-based reservation; the hard cap is the provider's." |
| 7:30 | Filter **Failover**, open the first row | "Model A failed, the gateway fell back inside the approved list, and the circuit breaker stopped retrying it." Show the raw audit record. |
| 9:00 | MCP angle (replay) | "The same controls apply whichever tool calls it: REST or any MCP client. Operator-only tools expose audit and usage." |
| 9:30 | Ask | A scoped pilot (below). |

## What you can and cannot claim

| You can say | Do not say |
|---|---|
| Routing, policy, content checks, budget reservations, cache, failover, ledger and audit are real code, tested end to end | "Production-ready" or "certified" |
| The dashboard's totals reconcile to the gateway's own records | Savings figures from simulated runs are real savings |
| Spend is bounded in layers, with the provider's hard limit as the true ceiling | The gateway guarantees a dollar cap |
| It exposes REST and local MCP; operator tools need an operator role | Remote or multi-tenant MCP is supported (it is refused on purpose) |
| Injection and PII detection are heuristic, with documented misses | It prevents data leakage |

## Questions you will get

**How does it plug into our existing AI ecosystem and enterprise infrastructure?**
Two doors today: a REST endpoint (`POST /v1/chat`) and a local MCP server, so any MCP-capable tool gets the same policy, budget and audit controls. Providers sit behind one interface (OpenAI and a mock exist; each additional provider needs an adapter). Be upfront about the integration gaps: identity is JWT with a shared secret (HS256) only, and production configuration rejects anything else, so an enterprise identity provider issuing asymmetric tokens needs JWKS support added first. Audit and usage are queryable through the API and stored in SQL; there is no SIEM or OpenTelemetry export yet. Storage is SQLite locally; PostgreSQL and Redis are the intended production path and are unverified.

**Is this real or a mock-up?**
The gateway is real and tested. The provider is simulated unless the badge says otherwise.

**Are the savings real?**
On scripted traffic against an all-premium baseline they illustrate the mechanism. Real savings need your traffic: propose a two-week shadow measurement that records what each request would have cost on each tier, then compare.

**What stops a runaway bill?**
Four layers (see the dashboard). The honest answer is that the provider's hard project limit is the only true ceiling, because the gateway reserves against an estimate and settles to the reported cost.

**What leaves the building?**
Prompts go to the model provider. The gateway can block personal data, credentials and injection attempts by policy per application, using heuristics with known misses. It makes no data-residency or DLP guarantee.

**Why not buy an off-the-shelf gateway?**
Such products exist. Do not claim this beats them; no comparison has been done. Position it as a reference implementation that pins down the requirements (policy, reservation-based budgets, audit, proof) and offer a build-versus-buy comparison against those requirements.

**What happens when a provider is down?**
Failover stays inside the approved candidate list and a circuit breaker stops retrying an unhealthy model; the dashboard shows this with a scripted outage in simulated runs. A live run cannot demonstrate it on cue.

**What would a pilot need?**
JWKS/asymmetric token verification against your identity provider, PostgreSQL and Redis with a concurrency test, audit export to your SIEM, an approved-prompt corpus to tune the injection heuristics, and a two-week shadow measurement.

## If something breaks live

Switch to the terminal replay, then say what you were about to show. Never improvise a number: every figure on the dashboard has a source row in the request table.
