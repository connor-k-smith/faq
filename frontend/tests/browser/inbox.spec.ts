import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

const counts = { total: 3, proposed_decision: 1, outcome_effect: 1, collecting: 1 };

test("owner navigates by badge through prioritized inbox to a stable question anchor", async ({ page }) => {
  await page.route("**/api/projects**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({ json: path === "/api/projects" ? [{ id: "project-1", name: "Atlas", description: null, archived: false }] : {
      project: { id: "project-1", name: "Atlas", description: null, archived: false }, read_only: false, initiatives: [],
    } });
  });
  await page.route("**/api/inbox**", async (route) => route.fulfill({ json: {
    counts, next_cursor: null, items: [
      item("proposed_decision", "proposal", "Review the proposal", "majority"),
      item("outcome_effect", "effect", "Record what changed", "unanimous"),
      item("collecting", "collecting", "Wait for responses", null),
    ],
  } }));

  await signIn(page);
  const inbox = page.getByRole("link", { name: /Inbox/ });
  await expect(inbox.getByLabel("3 open inbox items")).toBeVisible();
  await inbox.click();
  await expect(page).toHaveURL(/\/inbox$/);

  const headings = page.locator(".inbox-section h2");
  await expect(headings).toHaveText(["Decisions to review", "Outcome effect needed", "Still collecting"]);
  await expect(page.getByRole("heading", { name: "Decisions to review" }).locator("..", { hasText: "A deterministic proposal" })).toBeVisible();
  const question = page.getByRole("link", { name: /Review the proposal/ });
  await expect(question).toHaveAttribute("href", "/a/ask-1#question-proposal");
  await question.click();
  await expect(page).toHaveURL(/\/a\/ask-1#question-proposal$/);
});

function item(kind: string, question_id: string, question_prompt: string, decision_basis: string | null) {
  return { kind, project_name: "Atlas", initiative_name: "Record matching", ask_id: "ask-1",
    ask_title: "Confirm desired state", ask_status: "sent", question_id, question_ordinal: 0,
    question_prompt, question_status: "open", decision_basis, deadline: null, overdue: false,
    close_policy: "either" };
}
