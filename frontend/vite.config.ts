import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "virtual:auth-provider": resolve(import.meta.dirname, process.env.PLAYWRIGHT_AUTH_PROVIDER === "test" ? "tests/auth-provider.ts" : "src/auth-provider.ts"),
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8001",
      "/r": "http://127.0.0.1:8001",
      "/d": "http://127.0.0.1:8001",
      "/static": "http://127.0.0.1:8001",
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: "./src/test-setup.ts",
  },
});
