# Audited Purge

Owner: deploy administrator. A second deploy administrator must authorize execution.

1. Create a purge request through `/admin/purges/request` with exact `project` or `actor` scope and a ticketed reason.
2. Review the audit Event and calculate affected row counts using read-only operator inspection.
3. Obtain separate approval and use the privileged database path unavailable to the runtime/operator service accounts.
4. Persist execution evidence outside the deletion scope before deleting anything.
5. Verify application reads and search no longer return the scope, then record completion or failure.

Purge is not represented as immediate erasure from backups. Data can remain in 14 retained backups and seven days of PITR logs until those retention windows expire.
