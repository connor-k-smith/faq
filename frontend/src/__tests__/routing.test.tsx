import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";

import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

const session = { id: "member-1", display_name: "Member", organization_role: "member" };
const feed = { items: [], next_cursor: null, initiatives: [], askers: [] };

it("gives an administrator a path out of the empty project state", async () => {
  window.history.replaceState({}, "", "/");
  mockApi(async (input) => {
    if (String(input) === "/api/auth/session") return Response.json({ ...session, organization_role: "admin" });
    if (String(input) === "/api/projects") return Response.json([]);
    return Response.json({ counts: { total: 0 } });
  });

  renderApp();

  expect(await screen.findByRole("link", { name: "Open administration" })).toHaveAttribute("href", "/organization");
});

it("selects the feed route and preserves its project parameter", async () => {
  window.history.replaceState({}, "", "/p/project-42/feed");
  const fetch = mockApi(async (input) => Response.json(String(input) === "/api/auth/session" ? session : feed));

  renderApp();

  expect(await screen.findByRole("heading", { name: "Find the decision, not the thread." })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/api/projects/project-42/feed?", expect.anything());
});

it("redirects protected routes to login with the complete return URL", async () => {
  window.history.replaceState({}, "", "/a/ask-7?panel=results#decision");
  mockApi(async () => new Response(null, { status: 401 }));

  renderApp();

  await waitFor(() => expect(window.location.pathname).toBe("/login"));
  expect(new URLSearchParams(window.location.search).get("returnTo")).toBe("/a/ask-7?panel=results#decision");
  expect(screen.getByRole("heading", { name: "Continue to FAQ" })).toBeInTheDocument();
});

it("keeps feed filters tied to search history navigation", async () => {
  window.history.replaceState({}, "", "/p/project-1/feed?q=first");
  window.history.pushState({}, "", "/p/project-1/feed?q=second");
  mockApi(async (input) => Response.json(String(input) === "/api/auth/session" ? session : feed));

  renderApp();

  const input = await screen.findByLabelText("Search project memory");
  expect(input).toHaveValue("second");
  window.history.back();
  await waitFor(() => expect(input).toHaveValue("first"));

  fireEvent.change(input, { target: { value: "updated" } });
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(window.location.search).toBe("?q=updated"));
});
