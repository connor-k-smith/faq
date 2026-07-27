# Database Restore

Owner: FAQ operations. Target RPO: 5 minutes. Initial pilot RTO: 4 hours.

1. Declare the restore exercise or incident and record the source instance, backup ID, operator, and start time.
2. Create a disposable Cloud SQL instance in the same region. Never restore over production.
3. Restore the selected automated backup or PITR timestamp with `gcloud sql backups restore` or the approved Terraform workflow.
4. Run `scripts/restore-test.sh` with distinct `RESTORED_SQLALCHEMY_DATABASE_URL` and `RESTORED_LIBPQ_DATABASE_URL` values. Set and repeat the exact disposable database name, and provide a pre-recorded read-only sentinel query/value; the script refuses a name mismatch and checks migration head, invariants, validated foreign keys, and critical counts.
5. When an isolated application revision is available, set `RESTORE_APP_BASE_URL` and an authenticated historical Project or Decision export URL in `RESTORE_SMOKE_URL` with a short-lived `RESTORE_IDENTITY_TOKEN`. The script then checks readiness and the application-level read/export; without those values, this step remains manual and must not be recorded as automated evidence.
6. Record restore duration and evidence, then destroy the disposable service, credentials, and instance.

Automated backups retain 14 copies and PITR logs retain seven days. Purged data may remain recoverable until both windows expire.
