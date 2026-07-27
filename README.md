# FAQ

FAQ turns rough internal context into focused stakeholder questions and preserves the resulting
decisions by project and initiative. Authenticated collaborators author asks, stakeholders respond
through scoped links, and the resulting decisions remain attributable and searchable.

This project is under active development. Review the security and deployment model before using it
with sensitive information or exposing it to untrusted traffic.

## Capability and deployment status

| Area | Status |
| --- | --- |
| Local v1, Phases 1-4 | Implemented: invitation-gated authentication and administration; Project/Initiative access; assisted and manual Ask authoring; persisted recipient assignments; send, response, review, Decision, outcome sharing, history, jobs, and operator workflows. |
| Local verification | PostgreSQL/Alembic integration tests, frontend unit/browser tests, API contract generation, restore/route scripts, linting, typing, builds, and coverage reports are configured. |
| GCP resources | Terraform defines Firebase/Identity Platform, Cloud SQL, public/operator/jobs Cloud Run services, migration job, Scheduler, IAM, secrets, backups, and monitoring. |
| GCP application | Deployment-specific project IDs, domains, IAM principals, image digests, migration execution, route checks, and restore evidence are operator responsibilities. |

## Local development

Requirements: Python 3.13.7, uv 0.9.24, Node 22.22.0, and Docker.

```sh
cp .env.example .env
uv sync --frozen
npm ci --prefix frontend
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Run the frontend separately with `npm run dev --prefix frontend`. The database is exposed on
`localhost:55433` to avoid colliding with other local PostgreSQL installations.

Configure the Firebase web values in `.env`, then open `/login` and sign in with email/password.
The first verified identity matching `FAQ_BOOTSTRAP_ADMIN_EMAIL` becomes the initial administrator.
Administrators manage invitations and access from `/organization`. Local browser tests use a
test-only frontend provider and FastAPI entrypoint; the production application has no local-auth
bypass endpoints.

Production Terraform supplies `FAQ_JOBS_AUDIENCE` (the jobs Cloud Run URL),
`FAQ_JOBS_CALLER_EMAIL` (the Scheduler service-account email), `FAQ_OPERATOR_AUDIENCE` (the
operator Cloud Run URL), and `FAQ_OPERATOR_ALLOWED_EMAILS` (a JSON array of exact Google token
emails). Both private services verify the Google OIDC token received in `Authorization: Bearer`;
Cloud Run IAM remains the invocation perimeter.

The public Cloud Run service permits anonymous invocation and enforces respondent/Firebase
authentication in the application. Operator remains IAM-authenticated, and Scheduler is the only
jobs invoker. Deployment/state bootstrap, Firebase prerequisites, migration grants, and
validation commands are documented in `infra/README.md` and `docs/runbooks/migrations.md`. Keep
deployment values in ignored `.env` and `infra/terraform.tfvars` files; checked-in examples contain
placeholders only.

## Verification

```sh
uv run ruff check .
uv run mypy app tests
uv run pytest -m "not integration"  # unit
uv run pytest -m integration        # integration
uv run pytest                       # all backend tests
uv run pytest --cov=app --cov-report=term-missing --cov-report=html:coverage/backend
uv run alembic check
npm run lint --prefix frontend
npm run test --prefix frontend
npm run test:coverage --prefix frontend
npm run build --prefix frontend
npm run test:browser --prefix frontend
```

CI uploads backend XML/HTML and frontend LCOV reports without imposing a broad target. The current
local baseline is 87% backend statements and 68% frontend statements (71% frontend lines); use the
reports to prevent critical auth, operator, and jobs paths from regressing rather than excluding
uncovered code or inflating tests to satisfy an arbitrary repository-wide gate.

Pytest exclusively rebuilds and migrates `faq_test` before every test, including after code under
test commits on separate connections. Override connection details with `FAQ_TEST_DATABASE_URL`,
but its database name must remain exactly `faq_test`; URLs containing `production` are refused.
One pytest process may own this database at a time, so independent concurrent runs and xdist are
intentionally refused rather than sharing state.

The browser suite similarly rebuilds dedicated `faq_e2e`; configure its connection with
`FAQ_E2E_DATABASE_URL` (the database name must remain `faq_e2e`). Migration downgrade/upgrade
checks must use another disposable database, such as `faq_migration_test`, never `faq_test` or
`faq_e2e`. Docker PostgreSQL must be running before database-backed suites start.

## Contributing and security

See `CONTRIBUTING.md` for development and pull-request guidance. Report vulnerabilities privately
as described in `SECURITY.md`.

FAQ is available under the MIT License. See `LICENSE`.
