import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

export default function globalSetup() {
  const root = resolve(import.meta.dirname, "../../..");
  const databaseUrl = process.env.FAQ_E2E_DATABASE_URL ??
    "postgresql+psycopg://faq:faq@localhost:55433/faq_e2e";
  execFileSync("uv", ["run", "python", "-c", `
import os
import psycopg
from sqlalchemy.engine import make_url

url = make_url(os.environ["FAQ_E2E_DATABASE_URL"])
if url.database != "faq_e2e" or "production" in os.environ["FAQ_E2E_DATABASE_URL"].lower():
    raise SystemExit("FAQ_E2E_DATABASE_URL must target exactly faq_e2e and not contain production")
admin_url = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
with psycopg.connect(admin_url, autocommit=True) as connection:
    connection.execute("DROP DATABASE IF EXISTS faq_e2e WITH (FORCE)")
    connection.execute("CREATE DATABASE faq_e2e")
`], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, FAQ_E2E_DATABASE_URL: databaseUrl },
  });
  execFileSync("uv", ["run", "alembic", "upgrade", "head"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, FAQ_DATABASE_URL: databaseUrl },
  });
}
