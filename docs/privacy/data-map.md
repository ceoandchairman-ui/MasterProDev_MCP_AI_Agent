# Data map and vendor inventory (S20.1)

Status: draft for review. Vendor terms and data processing agreements are placeholders until the accounts exist.

## Personal data we hold

| Data | Where | Protection |
|---|---|---|
| Name, email, phone | `users` (encrypted); pending sign-ups in KV (encrypted) | Fernet encryption; blind indexes for lookup |
| Conversation text | `turns`, checkpoints, KV | Pseudonymized before storage; tokens resolve only in the same session |
| PII vault (token to real value) | KV, 7-day TTL (placeholder retention) | Encrypted values |
| Leads, quotes, funnel events | `leads`, `quotes`, `funnel_events` | Keyed by user id, no contact details |
| Long-term memories | in-process store today; pgvector planned | Consent-gated, no contact details |
| Google refresh tokens | `oauth_tokens` | Encrypted; access tokens cached 50 minutes, encrypted |
| Operational logs | stdout (JSON) | Secrets and personal data scrubbed before write |
| Traces and metrics | OpenTelemetry, Prometheus | Attributes scrubbed; metric labels contain no personal data |

## Vendors that may receive personal data

| Vendor | Receives | Our control | Status |
|---|---|---|---|
| LLM provider (HuggingFace router) | pseudonymized messages only (boundary B2 refuses raw data) | GuardedLLM | Placeholder: DPA needed |
| Embeddings endpoint | document chunks and queries (company content, pseudonymized queries) | pseudonymized before embedding | Placeholder: DPA needed |
| Twilio | phone numbers and message bodies (SMS and WhatsApp) | templates carry only the needed values | Placeholder: DPA needed |
| SendGrid | email address and message body | templates; no raw conversation text | Placeholder: DPA needed |
| Google (Calendar, Gmail) | the user's own calendar and mail, with the user's consent | per-user OAuth, scopes limited | Placeholder: Google verification |
| LangSmith (optional) | masked inputs and outputs only | mask_payload before upload; off without a key | Off until configured |
| Railway (hosting) | everything stored in our databases and volumes | encryption keys held in Railway variables | Placeholder: review terms |
| Stripe (later) | payment details entered on Stripe's page; we never see card numbers | Stripe-hosted checkout | Not in use |

## Retention (placeholders to decide)

- Conversations: undecided.
- Vault entries: 7 days.
- OTP codes: 10 minutes; pending sign-ups: 15 minutes.
- Backups: undecided; erasure does not purge backups until they age out.

## Open items

1. Confirm the privacy law that applies (PIPEDA, and GDPR if EU users are served) with counsel.
2. Sign the vendor DPAs listed above.
3. Decide the conversation and backup retention periods.
4. Run the erasure path against each vendor and record the result (the erasure report lists them).
