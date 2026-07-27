import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.mock("virtual:auth-provider", () => ({
    buttonLabel: "Sign in",
    credentialFields: true,
    credentialLabel: "Password",
    credentialType: "password",
  getIdentityToken: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});
