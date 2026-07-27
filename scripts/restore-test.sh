#!/bin/sh
set -eu

: "${RESTORED_SQLALCHEMY_DATABASE_URL:?Set the SQLAlchemy URL for the disposable restore}"
: "${RESTORED_LIBPQ_DATABASE_URL:?Set the libpq URL for psql}"
: "${RESTORE_ALLOWED_DATABASE_NAME:?Set the exact disposable database name}"
: "${RESTORE_CONFIRM_DATABASE_NAME:?Repeat the exact disposable database name to confirm}"
: "${RESTORE_SENTINEL_SQL:?Set a read-only SQL query returning one sentinel value}"
: "${RESTORE_SENTINEL_EXPECTED:?Set the expected sentinel value}"

test "$RESTORE_ALLOWED_DATABASE_NAME" = "$RESTORE_CONFIRM_DATABASE_NAME" || {
  printf '%s\n' "Restore target confirmation does not match." >&2
  exit 2
}

actual_database_name="$(psql "$RESTORED_LIBPQ_DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c 'SELECT current_database()')"
test "$actual_database_name" = "$RESTORE_ALLOWED_DATABASE_NAME" || {
  printf '%s\n' "Refusing unexpected database '$actual_database_name'." >&2
  exit 2
}

FAQ_DATABASE_URL="$RESTORED_SQLALCHEMY_DATABASE_URL" uv run alembic current
FAQ_DATABASE_URL="$RESTORED_SQLALCHEMY_DATABASE_URL" uv run alembic check
psql "$RESTORED_LIBPQ_DATABASE_URL" -X -v ON_ERROR_STOP=1 <<'SQL'
SELECT version_num FROM alembic_version;
SELECT count(*) AS organization_count FROM organization;
SELECT count(*) AS event_count FROM event;
SELECT count(*) AS committed_decision_count FROM decision WHERE state = 'committed';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM ask WHERE status IN ('draft', 'sent') AND closed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'live Ask has closed_at';
  END IF;
  IF EXISTS (SELECT 1 FROM decision WHERE state = 'committed' AND committed_at IS NULL) THEN
    RAISE EXCEPTION 'committed Decision lacks committed_at';
  END IF;
END $$;
SELECT conname, convalidated FROM pg_constraint WHERE contype = 'f' AND NOT convalidated;
SQL

unvalidated_fks="$(psql "$RESTORED_LIBPQ_DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND NOT convalidated")"
test "$unvalidated_fks" = "0"
sentinel="$(psql "$RESTORED_LIBPQ_DATABASE_URL" -XAt -v ON_ERROR_STOP=1 -c "$RESTORE_SENTINEL_SQL")"
test "$sentinel" = "$RESTORE_SENTINEL_EXPECTED" || {
  printf '%s\n' "Restore sentinel mismatch." >&2
  exit 3
}

if test -n "${RESTORE_APP_BASE_URL:-}"; then
  curl --fail --silent --show-error --max-time 10 "$RESTORE_APP_BASE_URL/readyz" >/dev/null
fi
if test -n "${RESTORE_SMOKE_URL:-}"; then
  : "${RESTORE_IDENTITY_TOKEN:?Set RESTORE_IDENTITY_TOKEN for the authenticated smoke/export URL}"
  curl --fail --silent --show-error --max-time 15 -H "Authorization: Bearer $RESTORE_IDENTITY_TOKEN" "$RESTORE_SMOKE_URL" >/dev/null
fi

printf '%s\n' "Restore validation passed. Record evidence and destroy the disposable target."
