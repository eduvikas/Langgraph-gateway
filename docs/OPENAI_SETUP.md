# OpenAI setup, screen by screen

Do this **before** the first real call in [REAL_PROVIDER.md](REAL_PROVIDER.md). It was written on 2026-10-30 from OpenAI's help pages and developer docs (linked inline). Dashboards change; if a label differs on screen, trust the screen and the linked guide.

## 1. Who can do what

Organization **Owners** can create and see all projects and keys. A project **Owner** can change project settings and set its spend limits; a project **Member** can make requests and create project-level keys ([managing projects](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform)). To set limits you need Owner rights on the project or organization.

## 2. Create a dedicated trial project

1. Open the **project selector** at the top of the platform and choose **Create project**.
2. Fill in the name (for example `ai-gateway-trial`), use case and business website, then create it.
3. Use this project for nothing else. Everything below happens inside it, so its limits and keys are your blast radius.

## 3. Create a project API key

1. **Organization settings** > select the trial project > **API Keys** > **+ Create new secret key**.
2. Name it for what it does (`gateway-local-trial`).
3. **Set an expiration date.** OpenAI [strongly recommends](https://developers.openai.com/api/docs/guides/production-best-practices) expiring project keys and rotating them.
4. **Permissions** offers **All**, **Restricted** and **Read Only** ([key permissions](https://help.openai.com/en/articles/8867743-assign-api-key-permissions)). The gateway only generates text through the Responses API, so *Restricted* with just the model-capability access it needs is the tidy choice. If a call fails with HTTP 403, widen it. On a dedicated trial project, *All* is acceptable because the project is the boundary. *Read Only* will not work.
5. Copy the key immediately into `.env` as `OPENAI_API_KEY`. Do not paste it into chats, tickets or the repository.

## 4. Set the monthly hard spend limit (the real ceiling)

From OpenAI's [spend limits guide](https://developers.openai.com/api/docs/guides/spend-limits):

1. **Project settings** > **Limits**.
2. In **Spend**, choose **Edit spend limit**.
3. Enter the **Monthly spend limit** (an amount you would shrug at for the whole trial).
4. Turn on **Enforce a hard limit**, then **Save**.

Know the behaviour: at a hard limit, requests fail with HTTP 429 (`project_spend_limit_exceeded`, or `organization_spend_limit_exceeded` for the organization limit). Enforcement is not instantaneous, so recorded spend can slightly exceed the number. Project limits cannot exceed the organization limit. An organization-wide limit lives at <https://platform.openai.com/settings/organization/limits>.

## 5. Add a spend alert

In the same **Spend** area, add an **alert** at a lower amount than the hard limit. An alert only sends a notification; it never stops traffic. The hard limit is what stops it.

## 6. Check credits and usage tier

- **Billing:** <https://platform.openai.com/settings/organization/billing>. If your account runs on prepaid credits, load only a small amount; running out returns `credit_balance_exhausted`.
- OpenAI also assigns an approved monthly **usage limit** by tier, separate from your spend limits (`organization_usage_limit_exceeded` when reached). See [Limits](https://platform.openai.com/settings/organization/limits).

## 7. Models and prices

The model catalog at <https://developers.openai.com/api/docs/models> lists the model IDs and per-million-token prices; the [pricing page](https://developers.openai.com/api/docs/pricing) covers long-context rates, cached input and tools. Models are served through the Responses API, which is what the gateway calls. On 2026-10-29 the catalog showed `gpt-6-astra` ($10/$50), `gpt-6.1-sol` ($2/$10), `gpt-6.1-terra` ($1/$5) and `gpt-6-luna` ($0.10/$0.50) per million input/output tokens. Confirm before you set `verified_on`.

## 8. What the gateway does when it talks to OpenAI

Read from `app/providers/openai_provider.py` and `app/gateway/graph.py`:

- It calls `responses.create` with your `MAX_OUTPUT_TOKENS` as `max_output_tokens`.
- The SDK client is created with `max_retries=0`: there are no hidden automatic retries that could bill twice.
- It requires token usage in the reply and refuses to price a reply without it.
- It rejects a reply from a different model than the one requested.
- Cost is computed from the tokens OpenAI reports, at the prices in `MODEL_PRICING_JSON`.
- It does not model cached-input discounts (it over-estimates, the safe direction) or the higher long-context rate; `MAX_PROMPT_CHARS` keeps prompts far below that range.

## 9. Error cheat sheet

| What you see | Meaning | What to do |
|---|---|---|
| 429 `project_spend_limit_exceeded` | Project hard limit reached | The safety net worked. Raise it only on purpose. |
| 429 `organization_spend_limit_exceeded` | Organization hard limit reached | Review the organization limits page. |
| 429 `organization_usage_limit_exceeded` | OpenAI's approved usage limit reached | Request a higher approved limit. |
| 429 `credit_balance_exhausted` | Prepaid credits used up | Add credits on the billing page. |
| 429 other | Rate limit | Wait and retry; see the [rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits). |
| 401 | Wrong, revoked or expired key | Create a new key, update `.env`. |
| 403 | Key or project lacks permission | Check key permissions and the project's model access. |
| 404 | Unknown model ID for this project | Compare `ALLOWED_MODELS` with the catalog. |

`python scripts/live_gateway_check.py --confirm` prints this advice automatically for the codes above.

## 10. Reconcile, rotate, revoke

- **Reconcile:** compare the token totals from `GET /v1/usage/recent` with <https://platform.openai.com/settings/organization/usage> for the project (it may lag).
- **Rotate:** create the replacement key, update `.env`, verify, then revoke the old key.
- **Emergency stop:** revoke the key in the project's **API Keys** page, or lower the project's hard limit.
