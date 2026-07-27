# Production Migrations

Owner: FAQ operations.

1. Build one immutable image and record its digest and source commit.
2. Review `alembic check`, upgrade SQL, lock behavior, and a tested forward-fix plan. Never use `downgrade base` outside disposable CI databases.
3. Confirm a recent backup and successful restore evidence.
4. Apply the reviewed Terraform plan, then execute the environment's Cloud Run migration Job using the same image digest.
5. Require successful Job completion before promoting either service. Verify `alembic current` equals `alembic heads`.
6. The job entrypoint runs `alembic upgrade head`, then transactionally reapplies grants for
   `faq_runtime`: database connect, schema usage, table DML, sequence usage/select, and migration
   owner's default privileges for future tables and sequences. It revokes Event UPDATE and DELETE;
   the application only inserts and reads Events. Audit immutability still needs database-enforced
   protection against migration-owner mutation and a reviewed purge design.
7. Confirm the runtime credential can perform application DML but cannot create or alter schema objects, update Events, or delete Events.
8. Deploy public, operator, and jobs with the same digest and run route, IAM, login, respondent, Scheduler, and Decision-export smoke checks.
9. On failure, stop promotion, preserve logs, roll back application traffic when schema-compatible, and prefer a reviewed forward migration over destructive downgrade.
