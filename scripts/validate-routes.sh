#!/bin/sh
set -eu

: "${PUBLIC_BASE_URL:?Set PUBLIC_BASE_URL}"
: "${OPERATOR_BASE_URL:?Set OPERATOR_BASE_URL}"
: "${JOBS_BASE_URL:?Set JOBS_BASE_URL}"

curl --fail --silent --show-error --max-time 10 "$PUBLIC_BASE_URL/healthz" >/dev/null
curl --fail --silent --show-error --max-time 10 "$PUBLIC_BASE_URL/readyz" >/dev/null
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$PUBLIC_BASE_URL/admin/health")" = "404"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$PUBLIC_BASE_URL/jobs/tick")" = "404"

operator_code="$(curl --silent --output /dev/null --write-out '%{http_code}' "$OPERATOR_BASE_URL/healthz")"
test "$operator_code" = "401" || test "$operator_code" = "403"
jobs_code="$(curl --silent --output /dev/null --write-out '%{http_code}' -X POST "$JOBS_BASE_URL/jobs/tick")"
test "$jobs_code" = "401" || test "$jobs_code" = "403"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$OPERATOR_BASE_URL/jobs/tick")" = "404"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$JOBS_BASE_URL/admin/health")" = "404"

if test -n "${OPERATOR_IDENTITY_TOKEN:-}"; then
  curl --fail --silent --show-error --max-time 10 -H "Authorization: Bearer $OPERATOR_IDENTITY_TOKEN" "$OPERATOR_BASE_URL/admin/inspect/projects" >/dev/null
fi
if test -n "${JOBS_IDENTITY_TOKEN:-}"; then
  curl --fail --silent --show-error --max-time 30 -X POST -H "Authorization: Bearer $JOBS_IDENTITY_TOKEN" "$JOBS_BASE_URL/jobs/tick" >/dev/null
fi

printf '%s\n' "Public/operator/jobs route matrix passed."
