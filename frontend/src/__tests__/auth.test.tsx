import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

it("presents production email and password sign-in", () => {
  window.history.replaceState({}, "", "/login");
  mockApi(async () => new Response(null, { status: 401 }));
  renderApp();

  expect(
    screen.getByRole("heading", { name: "Continue to FAQ" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Sign in" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Email")).toBeInTheDocument();
  expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
});
