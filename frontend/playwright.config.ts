import { defineConfig, devices } from "@playwright/test";

const databaseUrl = process.env.FAQ_E2E_DATABASE_URL ??
  "postgresql+psycopg://faq:faq@localhost:55433/faq_e2e";

export default defineConfig({
  testDir: "./tests/browser",
  globalSetup: "./tests/browser/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:4173", trace: "on-first-retry" },
  webServer: [
    {
      command: "uv run --directory .. uvicorn tests.auth_app:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/healthz",
      env: {
        FAQ_ENVIRONMENT: "test",
        FAQ_DATABASE_URL: databaseUrl,
        FAQ_BOOTSTRAP_ADMIN_EMAIL: "browser-admin@example.com",
        FAQ_SESSION_SECRET: "browser-test-session-secret-long-enough",
         FAQ_PUBLIC_BASE_URL: "http://127.0.0.1:4173",
         FAQ_ALL_RESPONDED_GRACE_MINUTES: "1",
       },
    },
    { command: "npm run dev -- --host 127.0.0.1 --port 4173", url: "http://127.0.0.1:4173", env: { PLAYWRIGHT_AUTH_PROVIDER: "test" } },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
