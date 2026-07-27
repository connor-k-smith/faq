import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

const project = { id: "project-1", name: "Atlas", description: "Planning platform", archived: false };

test("Project workspace navigates Initiatives on mobile", async ({ page }) => {
  await page.route("**/api/projects**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path === "/api/projects" ? [project] : {
      project,
      read_only: false,
      initiatives: [{
        id: "initiative-1",
        name: "Pool matching",
        kind: "feature",
        description: "Define the desired matching state.",
        archived: false,
        read_only: false,
        unresolved_count: 1,
        latest_activity_at: "2026-07-25T17:00:00Z",
        asks: [{ id: "ask-1", title: "Confirm desired state", status: "sent", created_at: "2026-07-25T17:00:00Z" }],
        recent_decisions: [],
      }],
    };
    await route.fulfill({ json: body });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);

  await expect(page.getByRole("heading", { name: "Atlas" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Active Initiatives" })).toContainText("Pool matching");
  await page.getByLabel("Initiative", { exact: true }).selectOption("initiative-1");
  await expect(page).toHaveURL(/\/p\/project-1\/i\/initiative-1$/);
  await expect(page.getByRole("heading", { name: "Pool matching", level: 1 })).toBeVisible();
});

test("manual Ask preview remains usable on mobile", async ({ page }) => {
  let sent = false;
  await page.route("**/api/asks/ask-1/assistant", async (route) => route.fulfill({ json: {
    kind: "clarification", authoring_session_id: "session-1", prompt_version: "draft-v1",
    clarification: { question: "Who decides which patients should match?", reason: "The decision owner is unclear." },
    draft: null, critiques: [],
  } }));
  await page.route("**/api/asks/ask-1/send", async (route) => {
    sent = true;
    await route.fulfill({ json: { ask: {}, artifacts: [{ recipient_id: "recipient-1", display_name: "Matt", url: "http://localhost/r/secret", message: "Hi Matt, please respond. http://localhost/r/secret" }] } });
  });
  await page.route("**/api/asks/ask-1", async (route) => route.fulfill({ json: {
    id: "ask-1", project_id: "project-1", initiative_id: "initiative-1",
    title: "Confirm desired state", intro: "Check the matching model.", deadline: null,
    default_note: null, owner_id: "owner-1", critiques_overridden: [],
    created_at: "2026-07-25T17:00:00Z", read_only: sent,
    project: { id: "project-1", name: "Atlas" },
    initiative: { id: "initiative-1", name: "Pool matching" },
    questions: [{ id: "question-1", template_id: "open_question", primitive: "text", version: 1, supersedes_question_id: null, ordinal: 0, prompt: "Which patients should match?", help_text: null, allow_comment: true, depends_on: null, response_visibility: "after_own_response", close_policy: "either", options: [], critiques_overridden: [] }],
    recipients: [{ id: "recipient-1", actor_id: "matt-1", display_name: "Matt", email: "matt@example.com", created_at: "2026-07-25T17:00:00Z", credential_active: sent, share_marked_sent_at: null }],
    recipient_previews: [],
    status: sent ? "sent" : "draft",
  } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await page.goto("/a/ask-1/edit");

  await expect(page.getByRole("heading", { name: "Shape the Ask." })).toBeVisible();
  await page.getByLabel("Source material").fill("Improve matching");
  await page.getByRole("button", { name: "Draft with agent" }).click();
  await expect(page.getByText("Who decides which patients should match?")).toBeVisible();
  await expect(page.getByLabel("Clarification answer")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Which patients should match?" })).toBeVisible();
  await page.getByText("Recipient preview").click();
  await expect(page.getByText("1 question assigned on send.")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  await expect(page.getByRole("heading", { name: "Share each personal invitation." })).toBeVisible();
  await expect(page.getByLabel("Share copy for Matt")).toHaveValue(/\/r\/secret/);
});

test("owner reviews and commits an outcome on mobile", async ({ page }) => {
  let closed = false;
  await page.route("**/api/asks/ask-1/results", async (route) => route.fulfill({ json: results(closed) }));
  await page.route("**/api/asks/ask-1/questions/question-1/decision", async (route) => {
    const body = route.request().postDataJSON();
    expect(body).toMatchObject({
      statement: "Use the confirmed matching cohort.",
      outcome_effect: "changed",
      share_with_recipients: true,
    });
    closed = true;
    await route.fulfill({ json: results(true) });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await page.goto("/a/ask-1");

  await expect(page.getByRole("heading", { name: "Confirm desired state" })).toBeVisible();
  await expect(page.getByText("Unanswered · pending")).toBeVisible();
  await page.getByRole("button", { name: "Stakeholder first" }).click();
  await expect(page.getByRole("alert")).toContainText("2 distinct IP addresses");
  await page.getByRole("button", { name: "Question first" }).click();
  await page.getByLabel("Canonical statement").fill("Use the confirmed matching cohort.");
  await page.getByLabel("Outcome effect").selectOption("changed");
  await page.getByLabel("What changed or became clearer?").fill("The cohort narrowed.");
  await page.getByLabel("Share this outcome with recipients").check();
  await page.getByRole("button", { name: "Commit Decision" }).click();

  await expect(page.getByText("The matching cohort is confirmed.")).toBeVisible();
  await expect(page.getByText("shared with recipients", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

function results(closed: boolean) {
  return {
    id: "ask-1", title: "Confirm desired state", status: closed ? "closed" : "sent",
    owner_id: "owner-1", sent_at: "2026-07-25T17:00:00Z", closed_at: closed ? "2026-07-25T19:00:00Z" : null,
    elapsed_seconds: 7200, can_decide: !closed,
    questions: [{
      id: "question-1", ordinal: 0, prompt: "Which patients should match?", primitive: "text",
      state: closed ? "closed" : "open", options: [], outcome_effect: closed ? "changed" : null,
      outcome_effect_note: closed ? "The cohort narrowed." : null,
      decision: closed ? { id: "decision-1", state: "committed", basis: "asker_judgment", statement: "The matching cohort is confirmed.", statement_source: "owner", value: null, committed_at: "2026-07-25T19:00:00Z", shared_with_recipients_at: "2026-07-25T19:00:00Z", substantive_evidence_count: 1, evidence: [{ response_id: "response-1", role: "determining" }], resolution: null } : null,
      assignments: [{ id: "assignment-1", recipient_id: "recipient-1", display_name: "Matt", state: "responded", elapsed_seconds: 900, distinct_ip_count: 2, response_visible: true, latest_response: { id: "response-1", version: 1, disposition: "answered", value: "Active trial candidates", comment: "Include screening status", created_at: "2026-07-25T17:15:00Z" }, revisions: [{ id: "response-1", version: 1, disposition: "answered", value: "Active trial candidates", comment: "Include screening status", created_at: "2026-07-25T17:15:00Z" }] }, { id: "assignment-2", recipient_id: "recipient-2", display_name: "April", state: "pending", elapsed_seconds: 7200, distinct_ip_count: 0, response_visible: true, latest_response: null, revisions: [] }],
    }],
    stakeholders: [{ recipient_id: "recipient-1", display_name: "Matt", distinct_ip_count: 2, questions: [{ question_id: "question-1", assignment_id: "assignment-1" }] }, { recipient_id: "recipient-2", display_name: "April", distinct_ip_count: 0, questions: [{ question_id: "question-1", assignment_id: "assignment-2" }] }],
  };
}
