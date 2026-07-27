import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

it("provides organization administration controls", async () => {
  window.history.replaceState({}, "", "/organization");
  mockApi(async (input) =>
    Response.json(
      String(input) === "/api/auth/session"
        ? {
            id: "owner-1",
            display_name: "Route Admin",
            organization_role: "admin",
          }
        : {
            actors: [
              {
                id: "owner-1",
                display_name: "Route Admin",
                email: "admin@example.com",
                role: "admin",
                authenticated: true,
                deactivated: false,
              },
            ],
            projects: [
              {
                id: "project-1",
                name: "Atlas",
                archived: false,
                membership_count: 1,
              },
            ],
            memberships: [
              { project_id: "project-1", actor_id: "owner-1", role: "Owner" },
            ],
            invitations: [
              {
                id: "invite-1",
                email: "new@example.com",
                expires_at: "2026-08-01T17:00:00Z",
              },
            ],
          },
    ),
  );
  renderApp();

  expect(
    await screen.findByRole("heading", { name: "Access, without ambiguity." }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Organization roster" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Route Admin")).toHaveLength(2);
  expect(screen.getByText("new@example.com")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Atlas" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
});

it("confirms authority and entity-specific destructive administration actions", async () => {
  window.history.replaceState({}, "", "/organization");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetch = mockApi(async (input) => Response.json(
    String(input) === "/api/auth/session"
      ? { id: "admin-1", display_name: "Admin", organization_role: "admin" }
      : {
          actors: [
            { id: "admin-1", display_name: "Admin", email: "admin@example.com", role: "admin", authenticated: true, deactivated: false },
            { id: "member-1", display_name: "Member", email: "member@example.com", role: "member", authenticated: true, deactivated: false },
          ],
          projects: [{ id: "project-1", name: "Atlas", archived: false, membership_count: 2 }],
          memberships: [
            { project_id: "project-1", actor_id: "admin-1", role: "Owner" },
            { project_id: "project-1", actor_id: "member-1", role: null },
          ],
          invitations: [{ id: "invite-1", email: "new@example.com", expires_at: "2026-08-01T17:00:00Z" }],
        },
  ));
  renderApp();
  await screen.findByRole("heading", { name: "Atlas" });

  fireEvent.click(screen.getByRole("button", { name: "Revoke invitation" }));
  expect(confirm).toHaveBeenLastCalledWith("Revoke the invitation for new@example.com?");
  fireEvent.click(screen.getByRole("button", { name: "Archive" }));
  expect(confirm).toHaveBeenLastCalledWith("Archive Project Atlas? It will become read-only.");
  fireEvent.click(screen.getByRole("button", { name: "Make member" }));
  expect(confirm).toHaveBeenLastCalledWith("Demote Admin to member? This changes their organization authority.");

  fireEvent.change(screen.getByLabelText("Transfer Member Asks to"), { target: { value: "admin-1" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[1]);
  expect(confirm).toHaveBeenLastCalledWith("Remove Member from this Project and transfer their live Asks to Admin?");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("retains membership grant values and shows an alert when the mutation fails", async () => {
  window.history.replaceState({}, "", "/organization");
  let rejectGrant: ((response: Response) => void) | undefined;
  mockApi(async (input, init) => {
    if (String(input).endsWith("/memberships") && init?.method === "POST") {
      return new Promise<Response>((resolve) => { rejectGrant = resolve; });
    }
    return Response.json(String(input) === "/api/auth/session"
      ? { id: "admin-1", display_name: "Admin", organization_role: "admin" }
      : {
          actors: [
            { id: "admin-1", display_name: "Admin", email: "admin@example.com", role: "admin", authenticated: true, deactivated: false },
            { id: "member-1", display_name: "Member", email: "member@example.com", role: "member", authenticated: true, deactivated: false },
          ],
          projects: [{ id: "project-1", name: "Atlas", archived: false, membership_count: 1 }],
          memberships: [{ project_id: "project-1", actor_id: "admin-1", role: "Owner" }],
          invitations: [],
        });
  });
  renderApp();
  const person = await screen.findByLabelText("New member for Atlas");
  fireEvent.change(person, { target: { value: "member-1" } });
  fireEvent.change(screen.getByLabelText("Project role for Atlas"), { target: { value: "Reviewer" } });
  fireEvent.click(screen.getByRole("button", { name: "Grant access" }));
  expect(await screen.findByRole("button", { name: "Granting..." })).toBeDisabled();
  rejectGrant?.(Response.json({ detail: "Grant rejected" }, { status: 409 }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Grant rejected");
  expect(person).toHaveValue("member-1");
  expect(screen.getByLabelText("Project role for Atlas")).toHaveValue("Reviewer");
  await waitFor(() => expect(screen.getByRole("button", { name: "Grant access" })).toBeEnabled());
});
