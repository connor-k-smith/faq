import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { proposalResultsFixture, resultsFixture } from "./fixtures";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

describe("review resolution", () => {
  beforeEach(() => window.history.replaceState({}, "", "/a/ask-1"));

  it("accepts late advisory input and excludes advisory Responses from evidence", async () => {
    let requestUrl = "";
    let requestBody: Record<string, unknown> | undefined;
    const advisoryResults = structuredClone(resultsFixture());
    Object.assign(advisoryResults.questions[0], {
      state: "closed",
      open_to: "project_members",
      can_contribute_advisory: true,
      decision: {
        id: "decision-advisory",
        state: "committed",
        basis: "majority",
        statement: "Include active candidates.",
        value: "Include active candidates.",
        committed_at: "2026-07-25T18:00:00Z",
        shared_with_recipients_at: null,
        substantive_evidence_count: 1,
        evidence: [],
        resolution: null,
        advisory_disagreement: true,
      },
    });
    const advisoryAssignment = structuredClone(
      advisoryResults.questions[0].assignments[0],
    );
    Object.assign(advisoryAssignment, {
      id: "assignment-advisory",
      recipient_id: "member-1",
      display_name: "Priya",
      origin: "unsolicited",
      late: true,
      latest_response: {
        id: "response-advisory",
        version: 1,
        disposition: "answered",
        value: "Include paused candidates.",
        comment: "",
        created_at: "2026-07-25T19:00:00Z",
      },
      revisions: [],
    });
    advisoryResults.questions[0].assignments.push(advisoryAssignment);
    mockApi(async (input, init) => {
      if (init?.method === "POST") {
        requestUrl = String(input);
        requestBody = JSON.parse(String(init.body));
      }
      return Response.json(advisoryResults);
    });
    renderApp();

    expect(
      await screen.findByText("Advisory · not asked directly"),
    ).toBeInTheDocument();
    expect(screen.getByText("Late")).toBeInTheDocument();
    expect(screen.getByText(/This is not a conflict/)).toBeInTheDocument();
    expect(screen.getByText("Primarily for: Matt, April.")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Evidence role for Priya"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Advisory response"), {
      target: { value: "Add clinical review." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add late advisory response" }),
    );

    await vi.waitFor(() =>
      expect(requestUrl).toBe(
        "/api/asks/ask-1/questions/question-1/advisory-responses",
      ),
    );
    expect(requestBody).toMatchObject({
      disposition: "answered",
      value: "Add clinical review.",
      comment: null,
    });
    expect(requestBody?.submission_id).toEqual(expect.any(String));
  });

  it("prefills and confirms a computed proposal by proposal id", async () => {
    let body: Record<string, unknown> | undefined;
    mockApi(async (_input, init) => {
      if (init?.method === "POST") body = JSON.parse(String(init.body));
      return Response.json(proposalResultsFixture());
    });
    renderApp();

    expect(await screen.findByLabelText("Canonical statement")).toHaveValue(
      "Approve the direction?: Approve.",
    );
    expect(screen.getByLabelText("Structured outcome")).toHaveValue("approve");
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm unchanged proposal" }),
    );
    await vi.waitFor(() =>
      expect(body).toMatchObject({
        proposal_id: "decision-1",
        value: "approve",
        evidence: [],
      }),
    );
  });

  it("labels a changed computed proposal as an owner override", async () => {
    mockApi(async () => Response.json(proposalResultsFixture()));
    renderApp();

    await screen.findByRole("button", { name: "Confirm unchanged proposal" });
    fireEvent.change(screen.getByLabelText("Structured outcome"), {
      target: { value: "reject" },
    });
    expect(
      screen.getByRole("button", { name: "Commit owner override" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Latest Responses used as evidence"),
    ).not.toBeInTheDocument();
  });

  it("explains conflict and no-response proposals", async () => {
    const conflict = proposalResultsFixture().questions[0];
    Reflect.set(conflict.decision!.resolution!, "computed_winner", false);
    Reflect.set(conflict.decision!.resolution!, "computed_value", null);
    Reflect.set(
      conflict.decision!.resolution!,
      "computed_basis",
      "asker_judgment",
    );
    Reflect.set(conflict.decision!.resolution!, "conflict", true);
    Reflect.set(conflict.decision!.resolution!, "vote_counts", {
      approve: 1,
      reject: 1,
    });
    const noResponse = structuredClone(conflict);
    Object.assign(noResponse, {
      id: "question-2",
      ordinal: 1,
      prompt: "No response?",
    });
    Object.assign(noResponse.decision!, { id: "decision-2" });
    Object.assign(noResponse.decision!.resolution!, {
      substantive_count: 0,
      conflict: false,
      vote_counts: {},
    });
    mockApi(async () =>
      Response.json({
        ...proposalResultsFixture(),
        questions: [conflict, noResponse],
      }),
    );
    renderApp();

    expect(
      await screen.findByText(
        "Responses conflict or are tied. Record the owner’s judgment.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No substantive responses were received. Record the owner’s judgment.",
      ),
    ).toBeInTheDocument();
  });

  it("records an outcome effect for an auto-committed decision", async () => {
    const data = proposalResultsFixture();
    data.questions[0].decision!.state = "committed";
    data.questions[0].decision!.resolution!.proposal_state = "committed";
    let requestUrl = "";
    let body: Record<string, unknown> | undefined;
    mockApi(async (input, init) => {
      if (init?.method === "POST") {
        requestUrl = String(input);
        body = JSON.parse(String(init.body));
      }
      return Response.json(data);
    });
    renderApp();

    expect(
      await screen.findByText("Approve the direction?: Approve."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Canonical Decision · complete"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Outcome effect"), {
      target: { value: "clarified" },
    });
    fireEvent.change(screen.getByLabelText("Effect note"), {
      target: { value: "The direction is explicit." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record outcome effect" }),
    );
    await vi.waitFor(() =>
      expect(requestUrl).toBe(
        "/api/asks/ask-1/questions/question-1/outcome-effect",
      ),
    );
    expect(body).toEqual({
      outcome_effect: "clarified",
      outcome_effect_note: "The direction is explicit.",
    });
  });
});
