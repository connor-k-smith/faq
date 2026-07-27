import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { draftFixture } from "./fixtures";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

describe("draft authoring", () => {
  beforeEach(() => window.history.replaceState({}, "", "/a/ask-1/edit"));

  it("renders the manual draft and recipient preview", async () => {
    mockApi(async () => Response.json(draftFixture()));
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Shape the Ask." }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ask title")).toHaveValue(
      "Confirm desired state",
    );
    expect(
      screen.getByRole("heading", { name: "Which patients should match?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Matt")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Recipient preview"));
    expect(
      screen.getByText("1 question assigned on send."),
    ).toBeInTheDocument();
  });

  it("creates, displays, edits, and removes Question dependencies", async () => {
    const draft = draftFixture();
    const dependentDraft = {
      ...draft,
      questions: [
        {
          ...draft.questions[0],
          template_id: "approval",
          primitive: "select_one",
          options: [
            { id: "option-1", value: "yes", label: "Yes", consequence: null },
            { id: "option-2", value: "no", label: "No", consequence: null },
          ],
        },
        {
          ...draft.questions[0],
          id: "question-2",
          ordinal: 1,
          prompt: "Explain the approval",
          depends_on: { question_id: "question-1", op: "eq", value: "yes" },
        },
      ],
    };
    const bodies: Record<string, unknown>[] = [];
    mockApi(async (_input, init) => {
      if (init?.body) bodies.push(JSON.parse(String(init.body)));
      return Response.json(dependentDraft);
    });
    renderApp();

    expect(
      await screen.findByText("Activates when Question 1 equals Yes."),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Edit Explain the approval" }),
    );
    expect(screen.getAllByLabelText("Prerequisite Question")[0]).toHaveValue(
      "question-1",
    );
    expect(screen.getAllByLabelText("Response visibility")[0]).toHaveValue(
      "after_own_response",
    );
    expect(screen.getAllByLabelText("Close policy")[0]).toHaveValue("either");
    fireEvent.change(screen.getByLabelText("Dependency condition"), {
      target: { value: "unanswered" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Question" }));
    await vi.waitFor(() =>
      expect(bodies.at(-1)).toMatchObject({
        depends_on: { question_id: "question-1", op: "unanswered" },
        response_visibility: "after_own_response",
        close_policy: "either",
      }),
    );

    fireEvent.change(screen.getByLabelText("Prerequisite Question"), {
      target: { value: "question-1" },
    });
    fireEvent.change(screen.getByLabelText("Dependency condition"), {
      target: { value: "in" },
    });
    fireEvent.change(screen.getByLabelText("Dependency value"), {
      target: { value: "yes" },
    });
    fireEvent.change(screen.getByLabelText("Prerequisite Question"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Question prompt"), {
      target: { value: "A new Question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Question" }));
    await vi.waitFor(() =>
      expect(bodies.at(-1)).toMatchObject({
        prompt: "A new Question",
        depends_on: null,
      }),
    );
  });

  it("authors Questions open to advisory Project member input", async () => {
    const bodies: Record<string, unknown>[] = [];
    mockApi(async (_input, init) => {
      if (init?.body) bodies.push(JSON.parse(String(init.body)));
      return Response.json(draftFixture());
    });
    renderApp();

    await screen.findByLabelText("Who may contribute");
    fireEvent.change(screen.getByLabelText("Who may contribute"), {
      target: { value: "project_members" },
    });
    fireEvent.change(screen.getByLabelText("Question prompt"), {
      target: { value: "What are we missing?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Question" }));

    await vi.waitFor(() =>
      expect(bodies.at(-1)).toMatchObject({ open_to: "project_members" }),
    );
  });

  it("continues a typed assistant clarification", async () => {
    mockApi(async (input, init) => {
      if (String(input).endsWith("/assistant") && init?.method === "POST") {
        return Response.json({
          kind: "clarification",
          authoring_session_id: "session-1",
          prompt_version: "draft-v2",
          clarification: {
            question: "Who decides which patients should match?",
            reason: "The decision owner is unclear.",
          },
          draft: null,
          critiques: [],
        });
      }
      return Response.json(draftFixture());
    });
    renderApp();

    await screen.findByLabelText("Source material");
    fireEvent.change(screen.getByLabelText("Source material"), {
      target: { value: "Improve matching" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Draft with agent" }));

    expect(
      await screen.findByText("Who decides which patients should match?"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Clarification answer")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Continue draft" }),
    ).toBeInTheDocument();
  });

  it("shows delegated Ask lineage without parent content and links both directions", async () => {
    window.history.replaceState({}, "", "/a/child-ask/edit");
    const draft = draftFixture();
    mockApi(async () =>
      Response.json({
        ...draft,
        id: "child-ask",
        parent_ask_id: "ask-1",
        title: "Delegated release question",
        status: "sent",
        read_only: true,
        questions: [
          {
            ...draft.questions[0],
            id: "child-question",
            copied_from_question_id: "question-1",
            depends_on: null,
          },
        ],
        recipients: [
          {
            ...draft.recipients[0],
            id: "child-recipient",
            display_name: "Sam Delegate",
            email: "sam@example.com",
            credential_active: true,
          },
        ],
      }),
    );
    renderApp();

    const notice = await screen.findByRole("region", { name: "Delegated Ask" });
    expect(notice).toHaveTextContent("Activation dependencies were cleared");
    expect(
      screen.getByRole("link", { name: "Back to parent Ask" }),
    ).toHaveAttribute("href", "/a/ask-1");
    expect(
      screen.getByText("Copied for delegation with dependencies cleared."),
    ).toBeInTheDocument();
    expect(screen.queryByText("April")).not.toBeInTheDocument();
  });
});
