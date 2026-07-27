import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { draftFixture } from "./fixtures";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

describe("draft delivery", () => {
  beforeEach(() => window.history.replaceState({}, "", "/a/ask-1/edit"));

  it("prepares personal share copy without persisting raw links", async () => {
    const draft = draftFixture();
    let sent = false;
    let revoked = false;
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockApi(async (input, init) => {
      if (init?.method === "DELETE") {
        revoked = true;
        return new Response(null, { status: 204 });
      }
      if (String(input).endsWith("/send") && init?.method === "POST") {
        sent = true;
        return Response.json({
          ask: { ...draft, status: "sent", read_only: true },
          artifacts: [
            {
              recipient_id: "recipient-1",
              display_name: "Matt",
              url: "http://localhost/r/secret",
              message: "Hi Matt, please respond. http://localhost/r/secret",
            },
          ],
        });
      }
      return Response.json(
        sent
          ? {
              ...draft,
              status: "sent",
              read_only: true,
              recipients: [{ ...draft.recipients[0], credential_active: true }],
            }
          : draft,
      );
    });
    renderApp();

    await screen.findByRole("button", { name: "Prepare to send" });
    fireEvent.click(screen.getByRole("button", { name: "Prepare to send" }));

    expect(
      await screen.findByRole("heading", {
        name: "Share each personal invitation.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View live results" }),
    ).toHaveAttribute("href", "/a/ask-1");
    expect(screen.getByLabelText("Share copy for Matt")).toHaveValue(
      "Hi Matt, please respond. http://localhost/r/secret",
    );
    expect(screen.getByLabelText("Mark Matt sent")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Revoke access" }));
    await vi.waitFor(() => expect(revoked).toBe(true));
  });

  it("shows recipient workload and requires Send anyway without sending early", async () => {
    const draft = draftFixture();
    const busyDraft = {
      ...draft,
      recipients: [
        {
          ...draft.recipients[0],
          open_assignments: 2,
          recent_assignments: 3,
          recent_asks: 2,
          workload_warning: true,
        },
      ],
    };
    let sendCount = 0;
    mockApi(async (input, init) => {
      if (String(input).endsWith("/send") && init?.method === "POST") {
        sendCount += 1;
        return Response.json({
          ask: { ...busyDraft, status: "sent" },
          artifacts: [],
        });
      }
      return Response.json(busyDraft);
    });
    renderApp();

    expect(
      await screen.findByText(
        "2 open · 3 assignments across 2 Asks in the last 7 days",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare to send" }));

    expect(sendCount).toBe(0);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Matt has existing or recent assignments",
    );
    fireEvent.click(screen.getByRole("button", { name: "Send anyway" }));
    await vi.waitFor(() => expect(sendCount).toBe(1));
  });

  it("uses sent mutation capabilities and shows only the new recipient artifact", async () => {
    const draft = draftFixture();
    const sentDraft = {
      ...draft,
      status: "sent",
      read_only: true,
      can_edit_questions: true,
      can_add_questions: true,
      can_add_recipients: true,
    };
    const bodies: Record<string, unknown>[] = [];
    let added = false;
    mockApi(async (input, init) => {
      if (init?.body) bodies.push(JSON.parse(String(init.body)));
      if (String(input).endsWith("/recipients") && init?.method === "POST") {
        added = true;
        return Response.json({
          recipient: {
            ...draft.recipients[0],
            id: "recipient-2",
            display_name: "New person",
          },
          artifact: {
            recipient_id: "recipient-2",
            display_name: "New person",
            url: "http://localhost/r/unique",
            message: "Unique new invitation http://localhost/r/unique",
          },
        });
      }
      return Response.json(
        added
          ? {
              ...sentDraft,
              recipients: [
                ...draft.recipients,
                {
                  ...draft.recipients[0],
                  id: "recipient-2",
                  display_name: "New person",
                },
              ],
            }
          : sentDraft,
      );
    });
    renderApp();

    expect(
      await screen.findByText(/existing recipient roster is immutable/i),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Stakeholder name"), {
      target: { value: "New person" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add stakeholder" }));

    expect(
      await screen.findByDisplayValue(/Unique new invitation/),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Share copy for Matt"),
    ).not.toBeInTheDocument();
    expect(bodies.at(-1)).toMatchObject({
      display_name: "New person",
      question_ids: ["question-1"],
    });
  });
});
