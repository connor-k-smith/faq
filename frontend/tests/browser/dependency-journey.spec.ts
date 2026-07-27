import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("dependent Question activates and withdraws through the no-JS respondent flow", async ({ browser, page }) => {
  test.setTimeout(60_000);

  await signIn(page, "Dependency Author");

  await page.goto("/organization");
  await page.getByLabel("Project name").fill("Dependency Project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const projectCard = page.locator(".project-access-card", { hasText: "Dependency Project" });
  await projectCard.getByLabel("New member for Dependency Project").selectOption({ index: 1 });
  await projectCard.getByLabel("Project role for Dependency Project").fill("Owner");
  await projectCard.getByRole("button", { name: "Grant access" }).click();

  await page.goto("/");
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Conditional rollout");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await page.getByRole("button", { name: "Start an Ask" }).click();

  await page.getByLabel("Ask title").fill("Confirm rollout readiness");
  await page.getByLabel("Framing for stakeholders").fill("Confirm whether rollout planning should continue.");
  await page.getByRole("button", { name: "Save details" }).click();

  await page.getByLabel("Question format").selectOption("approval");
  await page.getByLabel("Question prompt").fill("Is the rollout ready?");
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.getByRole("heading", { name: "Is the rollout ready?" })).toBeVisible();

  await page.getByLabel("Question format").selectOption("open_question");
  await page.getByLabel("Question prompt").fill("What is the rollout plan?");
  await page.getByLabel("Prerequisite Question").selectOption({ label: "Question 1: Is the rollout ready?" });
  await page.getByLabel("Dependency condition").selectOption("eq");
  await page.getByLabel("Dependency value").selectOption({ label: "Yes" });
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.getByText("Activates when Question 1 equals Yes.")).toBeVisible();

  await page.getByLabel("Stakeholder name").fill("Respondent");
  await page.getByLabel("Stakeholder email").fill("respondent@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  const shareCopy = await page.getByLabel("Share copy for Respondent").inputValue();
  const invitationUrl = shareCopy.match(/https?:\/\/\S+/)?.[0];
  expect(invitationUrl).toBeTruthy();

  const respondent = await browser.newContext({ javaScriptEnabled: false });
  const respondentPage = await respondent.newPage();
  await respondentPage.goto(invitationUrl!);
  await expect(respondentPage.getByRole("heading", { name: "Is the rollout ready?" })).toBeVisible();
  await expect(respondentPage.getByText("What is the rollout plan?")).toHaveCount(0);
  await expect(respondentPage.getByText("0 of 1 questions answered.")).toBeVisible();

  const prerequisite = respondentPage.locator(".question", { hasText: "Is the rollout ready?" });
  await prerequisite.getByRole("radio", { name: "Yes", exact: true }).check();
  await prerequisite.getByRole("button", { name: "Save answer" }).click();
  await expect(respondentPage.getByRole("heading", { name: "What is the rollout plan?" })).toBeVisible();
  await expect(respondentPage.getByText("1 of 2 questions answered.")).toBeVisible();

  const revisedPrerequisite = respondentPage.locator(".question", { hasText: "Is the rollout ready?" });
  await revisedPrerequisite.getByRole("radio", { name: "No", exact: true }).check();
  await revisedPrerequisite.getByRole("button", { name: "Save revision" }).click();
  await expect(respondentPage.getByText("What is the rollout plan?")).toHaveCount(0);
  await expect(respondentPage.getByText("All assigned questions are complete.", { exact: false })).toBeVisible();

  await respondent.close();
});
