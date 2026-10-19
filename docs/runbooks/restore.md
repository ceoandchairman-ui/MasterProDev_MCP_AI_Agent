# Backup and restore runbook

Targets to confirm with the owner: RPO 24 hours, RTO 1 hour. The drill below is how the RTO gets measured.

## Backups
`scripts/backup_postgres.sh` takes a logical dump (`pg_dump --format=custom`), writes a SHA-256 checksum beside it and
keeps the newest `BACKUP_KEEP` dumps (default 14).

```
DATABASE_URL=<production connection string> BACKUP_DIR=<off-platform location> scripts/backup_postgres.sh
```
Run it on a schedule (daily meets a 24 hour RPO). `BACKUP_DIR` must be outside Railway, otherwise losing the platform
loses the backups too. Not yet scheduled or automated: that is a deployment task.

What is not in the dump: Redis (sessions' hot copies, one-time codes, the privacy vault, caches, rate limits) is
disposable by design. After a restore, people sign in again and in-flight verification codes are re-requested.

## Restore drill (run at least quarterly, and after any schema migration)
```
SCRATCH_DATABASE_URL=<empty scratch database> BACKUP_DIR=<same location> scripts/restore_drill.sh
```
It verifies the checksum, restores the newest dump into the scratch database and prints row counts for `tenants`,
`users` and `sessions`. Never point `SCRATCH_DATABASE_URL` at production. Write down the elapsed time: that is your
measured RTO for the database portion.

After restoring into a scratch database, also confirm the pgvector extension exists (`CREATE EXTENSION IF NOT EXISTS vector`)
and run `alembic upgrade head` to check the schema is current.

## Restoring production
1. Decide the restore point (newest dump unless you know the corruption time).
2. Put the api in maintenance by scaling it to zero replicas in Railway so nothing writes during the restore.
3. Restore into a new Postgres service first and check it (row counts, `alembic current`); only then repoint `DATABASE_URL`.
   Do not restore over the live database unless it is already lost.
4. Re-run the knowledge index if the dump predates recent documents: `python -m mpd_assistant.worker.main --once reindex`.
5. Scale the api back up, then watch `/health` and the error rate.
6. Anything between the dump and the failure is lost (up to the RPO). Payments made in that window exist in Stripe;
   reconcile them against the restored quotes before telling anyone the system is whole.

## Erased data and backups
Erasure requests (`scripts/dsr.py erase`) do not rewrite old backups. They age out under the backup retention
(`BACKUP_KEEP` days). After restoring a backup, people erased since its date reappear. The erasure audit entries live
in the same database, so the restore rolls them back too: keep your own record of each erasure request (who, when,
user id) outside the database, and re-run `scripts/dsr.py erase` for each one made since the backup date.
