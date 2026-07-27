import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

it("renders the prioritized owner inbox with question links", async () => {
  window.history.replaceState({}, "", "/inbox");
  mockApi(async () =>
    Response.json({
      counts: {
        total: 2,
        proposed_decision: 1,
        outcome_effect: 0,
        collecting: 1,
      },
      next_cursor: null,
      items: [
        {
          kind: "proposed_decision",
          project_name: "Atlas",
          initiative_name: "Pool matching",
          ask_id: "ask-1",
          ask_title: "Confirm desired state",
          ask_status: "sent",
          question_id: "question-1",
          question_ordinal: 0,
          question_prompt: "Which patients should match?",
          question_status: "open",
          decision_basis: "majority",
          deadline: "2026-07-25T17:00:00Z",
          overdue: true,
          close_policy: "either",
        },
      ],
    }),
  );
  renderApp();

  expect(
    await screen.findByRole("heading", { name: "Inbox" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Decisions to review" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /Which patients should match/ }),
  ).toHaveAttribute("href", "/a/ask-1#question-question-1");
  expect(screen.getByText(/Everyone responds or deadline/)).toBeInTheDocument();
});
