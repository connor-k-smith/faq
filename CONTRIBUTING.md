# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Development

Follow the local setup in `README.md`. Before submitting a change, run the checks relevant to it:

```sh
uv run ruff check .
uv run mypy app tests
uv run pytest
npm run lint --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
terraform -chdir=infra fmt -check
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```

Database-backed and browser tests require the local PostgreSQL service described in `README.md`.

Keep pull requests focused, include tests for behavioral changes, and update generated OpenAPI
artifacts with `npm run contract:generate --prefix frontend` when the API contract changes.

## Configuration and credentials

Never commit `.env`, `terraform.tfvars`, Terraform state, Firebase configuration, cloud credential
files, respondent links, or production data. Use synthetic names and `example.com` addresses in
tests and documentation.

Report vulnerabilities privately as described in `SECURITY.md` rather than opening a public issue.
