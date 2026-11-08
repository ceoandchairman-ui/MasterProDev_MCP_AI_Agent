# Key rotation runbook

Generate new keys with `python -c "from mpd_assistant.core.crypto import generate_key; print(generate_key())"`.
Secrets live only in Railway variables. Rotating `HUGGINGFACE_API_KEY` or any other provider key is not urgent unless it
leaked: add the new value, redeploy, revoke the old one at the provider.

## DATA_ENCRYPTION_KEY (encrypts names, emails, phones and Google refresh tokens)
Several keys can be active at once: the first encrypts, all decrypt.
1. Take a backup (`scripts/backup_postgres.sh`).
2. In Railway set `DATA_ENCRYPTION_KEY=<new key>` and `DATA_ENCRYPTION_KEYS_PREVIOUS=<old key>`. Deploy. The app now writes with the new key and still reads old data.
3. Dry run: `python scripts/rotate_keys.py encryption` (prints counts, changes nothing).
4. Apply: `python scripts/rotate_keys.py encryption --apply`. Run it again; a second run should report `rotated=0`.
5. Only when `failed=0` and a second run rotated nothing: remove `DATA_ENCRYPTION_KEYS_PREVIOUS` and redeploy.
6. Keep the old key somewhere safe until the oldest backup that was encrypted with it has aged out; restoring that backup needs it.

If `failed` is not zero, those rows could not be decrypted with any configured key. Do not remove the old key. Row ids
are printed (never values); find which key is missing.

## BLIND_INDEX_KEY (lookup indexes for email and phone)
An index is a keyed hash and cannot be converted, only recomputed, and people cannot be found by email or phone while
the stored indexes and the configured key disagree. Do this in a short maintenance window.
1. Backup. Scale the api to zero (or accept a few minutes where sign-in lookups fail).
2. `python scripts/rotate_keys.py blind-index --new-key <new key>` (dry run), then add `--apply`.
3. Immediately set `BLIND_INDEX_KEY=<new key>` in Railway and redeploy.
4. Short-lived Redis entries keyed by the old index (channel session maps) expire on their own within a week.

## SECRET_KEY (one-time codes)
Changing it only invalidates codes that are in flight. Set the new value and redeploy.

## MCP_SERVICE_KEY (api to tool servers)
The api and every tool server (`mcp-calendar`, `mcp-gmail`, `mcp-quoting`, `mcp-db`) must hold the same value. Change
all of them together in Railway and redeploy them together; during the gap, tool calls fail with 401.

## Tokens
`METRICS_TOKEN`, `ADMIN_TOKEN`, `EMAIL_INBOUND_TOKEN`: change the variable and the other side at the same time
(Prometheus config, the staff browser or tool, the SendGrid Inbound Parse URL).
`STRIPE_WEBHOOK_SECRET`: roll it in the Stripe dashboard, which gives a short overlap, then update the variable.
`TWILIO_AUTH_TOKEN`: rotate in Twilio, update the variable; inbound webhooks fail signature checks until you do.
