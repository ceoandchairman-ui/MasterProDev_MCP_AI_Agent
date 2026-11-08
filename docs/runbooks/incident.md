# Incident runbook

Single production environment on Railway. Nothing here has been drilled against live services yet; treat the
"what to expect" lines as the design intent and correct them after the first drill.

## First five minutes
1. Is the API up? `GET /health` on the public domain returns `{"status": "ok"}`. If not, open the api service logs in Railway.
2. What changed? Check the latest deploy (Railway) and the last commit on `main`. If the problem started with a deploy, roll back to the previous deployment in Railway first, investigate second.
3. Look at the metrics (`GET /metrics` with the `METRICS_TOKEN` bearer token, or the Grafana dashboards):
   - `mpd_turn_latency_seconds` rising: model or database slowness.
   - `mpd_eval_verdicts_total{verdict!="pass"}` rising: the model is returning bad output; check the model provider.
   - `mpd_budget_blocks_total` rising: a token budget is exhausted (daily limits, see `SESSION_DAILY_TOKENS` and `GLOBAL_DAILY_TOKENS`).
   - `mpd_pii_detections_total` any increase: raw personal data was caught at a boundary (`B2_llm_egress` = refused before reaching the model; `B7_reply` = found in a reply). `mpd_eval_reasons_total{reason="pii_leak"}` counts replies replaced because of it. A caught leak is the control working; investigate the cause, and treat any sign it got through as a privacy incident (below).
   - `mpd_escalations_total` spike: many conversations are being handed to people.

## What each dependency does when it is down (design intent, not yet drilled)
| Down | Effect |
|---|---|
| Model provider | Replies fall back to a templated "please try again" message; escalation to a person still works. |
| Postgres | Sessions, memory, quotes and knowledge search fail. Chat degrades; the app does not start in production without the database. |
| Redis | Rate limits, one-time codes, the privacy vault and checkpoints fail; chat is expected to error. Only the response cache fails soft. |
| Twilio / SendGrid | Verification codes and confirmations cannot be delivered; the notification service reports `failed`. |
| Stripe | New checkouts fail with a message to contact the team; existing payments are unaffected. Payment confirmation arrives later through the webhook. |

## People waiting for a human
`python scripts/escalations.py list` shows open escalations; `resolve <reference>` lets the assistant answer that conversation again. The admin routes under `/v2/admin/` (bearer `ADMIN_TOKEN`) do the same.

## Privacy incident (raw personal data where it should not be)
1. Stop the spread: if the data is in a log or trace source, restrict access to it now; if the leak is on a code path, roll back the deploy that introduced it.
2. Find what was exposed using `docs/privacy/data-map.md` (where personal data may and may not be) and the leak-canary tests in `tests/privacy` to reproduce the path.
3. Affected people: contact them through the stored user record; erase on request with `python scripts/dsr.py erase <user_id>`.
4. Vendors that held the data (model provider, tracing, email/SMS) are deleted by hand; erasure reports list them under `vendors_to_notify`.
5. Whether this is reportable under the privacy law that applies to the business is a decision for the owner and counsel, not this document.

## Payments
A payment that does not appear as paid: look for `mpd_payments_total{event="invalid_signature"}` (wrong `STRIPE_WEBHOOK_SECRET`) or `event="mismatch"` (amount or currency differs from the stored quote; the quote is held as `payment_review`, and staff are alerted once the mismatch callback is wired to the escalation flow). Never mark a quote paid by hand in the database without matching it to a Stripe payment.

## After the incident
Record what happened, how long it took to notice and fix, and any monitoring gap. Add an alert if one would have caught it earlier.
