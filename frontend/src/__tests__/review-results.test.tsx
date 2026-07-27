import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { draftFixture, resultsFixture } from "./fixtures";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

describe("review results", () => {
  beforeEach(() => window.history.replaceState({}, "", "/a/ask-1"));

  it("labels superseded and current correction Decisions distinctly", async () => {
    const results = resultsFixture();
    const historical = structuredClone(results);
    Object.assign(historical, { status: "closed", can_decide: false });
    Object.assign(historical.questions[0], {
      state: "closed",
      outcome_effect: "changed",
      decision: {
        id: "decision-1",
        state: "superseded",
        basis: "asker_judgment",
        statement: "Old outcome",
        value: null,
        committed_at: "2026-07-25T18:00:00Z",
        shared_with_recipients_at: null,
        substantive_evidence_count: 1,
        evidence: [],
        resolution: null,
        advisory_disagreement: false,
        supersedes_decision_id: null,
        successor_decision_id: "decision-2",
        historical: true,
      },
    });
    mockApi(async (input) =>
      Response.json(
        String(input).endsWith("/results")
          ? historical
          : {
              ...draftFixture(),
              status: "closed",
              read_only: true,
              can_create_successor: false,
            },
      ),
    );
    renderApp();

    expect(
      await screen.findByText("Historical Decision · superseded"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Export current Decision" }),
    ).toHaveAttribute("href", "/d/decision-2.md");
  });

  it("reviews live results in both orientations and commits an outcome", async () => {
    const results = resultsFixture();
    let commitBody: Record<string, unknown> | undefined;
    mockApi(async (_input, init) => {
      if (init?.method === "POST") commitBody = JSON.parse(String(init.body));
      return Response.json(results);
    });
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Confirm desired state" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Manage invitations" }),
    ).toHaveAttribute("href", "/a/ask-1/edit");
    expect(
      screen.getByText("Use active trial candidates."),
    ).toBeInTheDocument();
    expect(screen.getByText("Unanswered · pending")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stakeholder first" }));
    expect(
      screen.getByRole("region", { name: "Stakeholder results" }),
    ).toHaveTextContent("Matt");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "2 distinct IP addresses",
    );

    fireEvent.click(screen.getByRole("button", { name: "Question first" }));
    fireEvent.change(screen.getByLabelText("Canonical statement"), {
      target: { value: "Use the confirmed matching cohort." },
    });
    fireEvent.change(screen.getByLabelText("Outcome effect"), {
      target: { value: "changed" },
    });
    expect(
      screen.getByLabelText("What changed or became clearer?"),
    ).toBeRequired();
    fireEvent.change(screen.getByLabelText("What changed or became clearer?"), {
      target: { value: "The eligible cohort narrowed." },
    });
    fireEvent.click(
      screen.getByLabelText("Share this outcome with recipients"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Commit Decision" }));

    await vi.waitFor(() =>
      expect(commitBody).toMatchObject({
        statement: "Use the confirmed matching cohort.",
        outcome_effect: "changed",
        outcome_effect_note: "The eligible cohort narrowed.",
        share_with_recipients: true,
        evidence: [{ response_id: "response-1", role: "determining" }],
      }),
    );
  });

  it("labels a parent delegation non-substantive and links to its child Ask", async () => {
    const delegated = structuredClone(resultsFixture());
    Object.assign(delegated.questions[0].assignments[0], {
      delegated_to_actor_id: "delegate-1",
      child_ask_id: "child-ask",
      latest_response: {
        ...delegated.questions[0].assignments[0].latest_response!,
        disposition: "delegated",
        value: null,
      },
    });
    mockApi(async () => Response.json(delegated));
    renderApp();

    expect(
      await screen.findByText("Delegated, non-substantive response"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open delegated Ask" }),
    ).toHaveAttribute("href", "/a/child-ask");
  });

  it("labels owner judgment without substantive stakeholder evidence", async () => {
    const results = resultsFixture();
    mockApi(async () =>
      Response.json({
        ...results,
        status: "closed",
        can_decide: false,
        questions: [
          {
            ...results.questions[0],
            state: "closed",
            outcome_effect: "clarified",
            outcome_effect_note: "Operations owns the follow-up.",
            decision: {
              id: "decision-manual",
              state: "committed",
              basis: "asker_judgment",
              statement: "Operations will define the matching cohort.",
              value: null,
              committed_at: "2026-07-25T18:00:00Z",
              shared_with_recipients_at: null,
              substantive_evidence_count: 0,
              evidence: [],
              resolution: null,
            },
          },
        ],
      }),
    );
    renderApp();

    expect(
      await screen.findByText(
        "Owner judgment without a substantive stakeholder response.",
      ),
    ).toBeInTheDocument();
  });
});
