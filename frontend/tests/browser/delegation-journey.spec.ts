import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("Phase 4.2 delegation creates an isolated child credential journey", async ({ browser, page }) => {
  test.setTimeout(90_000);
  await signIn(page);

  await page.goto("/organization");
  await page.getByLabel("Project name").fill("Delegation Project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const project = page.locator(".project-access-card", { hasText: "Delegation Project" });
  await project.getByLabel("New member for Delegation Project").selectOption({ label: "Browser Admin" });
  await project.getByRole("button", { name: "Grant access" }).click();

  await page.goto("/");
  await page.getByLabel("Project", { exact: true }).selectOption({ label: "Delegation Project" });
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Delegated review");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await page.getByRole("button", { name: "Start an Ask" }).click();
  await page.getByLabel("Ask title").fill("Choose a rollout owner");
  await page.getByLabel("Framing for stakeholders").fill("PARENT PRIVATE FRAMING");
  await page.getByRole("button", { name: "Save details" }).click();
  await page.getByLabel("Question prompt").fill("Who should own the rollout?");
  await page.getByRole("button", { name: "Add Question" }).click();
  await page.getByLabel("Stakeholder name").fill("Original Respondent");
  await page.getByLabel("Stakeholder email").fill("original@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  const parentCopy = await page.getByLabel("Share copy for Original Respondent").inputValue();
  const parentUrl = invitationUrl(parentCopy);

  const original = await browser.newContext({ javaScriptEnabled: false });
  const originalPage = await original.newPage();
  await originalPage.goto(parentUrl);
  const question = originalPage.locator(".question", { hasText: "Who should own the rollout?" });
  await question.getByLabel("Response type").selectOption("delegated");
  await question.getByLabel("Delegate display name").fill("New Stakeholder");
  await question.getByLabel("Delegate email").fill("new-stakeholder@example.com");
  await question.getByLabel("Comment or delegation recommendation").fill("PARENT HANDOFF COMMENT");
  await question.getByRole("button", { name: "Save answer" }).click();

  await page.getByRole("link", { name: "View live results" }).click();
  await expect(page.getByText("Delegated, non-substantive response")).toBeVisible();
  await page.getByRole("link", { name: "Open delegated Ask" }).click();
  await expect(page.getByRole("region", { name: "Delegated Ask" })).toBeVisible();
  await expect(page.getByText("PARENT HANDOFF COMMENT")).toHaveCount(0);
  await expect(page.getByText("Original Respondent", { exact: true })).toHaveCount(0);

  await page.goto(`${page.url()}/edit`);
  await expect(page.getByText("The raw link is only shown when issued.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Reissue link" }).click();
  const childCopy = await page.getByLabel("Share copy for New Stakeholder").inputValue();
  const childUrl = invitationUrl(childCopy);

  const delegate = await browser.newContext({ javaScriptEnabled: false });
  const delegatePage = await delegate.newPage();
  await delegatePage.goto(childUrl);
  await expect(delegatePage.getByText("PARENT PRIVATE FRAMING")).toBeVisible();
  await expect(delegatePage.getByText("PARENT HANDOFF COMMENT")).toHaveCount(0);
  await expect(delegatePage.getByText("Original Respondent", { exact: true })).toHaveCount(0);
  await delegatePage.getByLabel("Your answer").fill("New Stakeholder owns rollout.");
  await delegatePage.getByRole("button", { name: "Save answer" }).click();
  await expect(delegatePage.getByText("Saved response, version 1")).toBeVisible();

  await page.getByRole("link", { name: "Back to parent Ask" }).click();
  const parentQuestion = page.locator(".result-question", { hasText: "Who should own the rollout?" });
  await parentQuestion.getByLabel("Canonical statement").fill("The owner will coordinate rollout separately.");
  await parentQuestion.getByRole("button", { name: "Commit Decision" }).click();
  await expect(page.locator(".draft-state")).toHaveText("closed");

  await page.getByRole("link", { name: "Open delegated Ask" }).click();
  await expect(page.locator(".draft-state")).toHaveText("sent");
  await expect(page.getByText("New Stakeholder owns rollout.")).toBeVisible();
  await original.close();
  await delegate.close();
});

function invitationUrl(message: string) {
  const url = message.match(/https?:\/\/\S+/)?.[0];
  if (!url) throw new Error("Invitation URL missing from share copy");
  return url;
}
