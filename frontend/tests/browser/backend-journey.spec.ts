import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("real backend journey from administration through Ask closure", async ({ browser, page }) => {
  test.setTimeout(60_000);

  await signIn(page);

  await page.goto("/organization");
  await expect(page.getByRole("heading", { name: "Access, without ambiguity." })).toBeVisible();
  await page.getByLabel("Project name").fill("Browser Project");
  await page.getByLabel("Description").fill("End-to-end product verification");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const projectCard = page.locator(".project-access-card", { hasText: "Browser Project" });
  await projectCard.getByLabel("New member for Browser Project").selectOption({ label: "Browser Admin" });
  await projectCard.getByLabel("Project role for Browser Project").fill("Owner");
  await projectCard.getByRole("button", { name: "Grant access" }).click();
  await expect(projectCard.getByText("Browser Admin")).toBeVisible();

  await page.goto("/");
  await page.getByLabel("Project", { exact: true }).selectOption({ label: "Browser Project" });
  await expect(page.getByRole("heading", { name: "Browser Project" })).toBeVisible();
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Launch readiness");
  await page.getByLabel("Description").fill("Resolve the release direction.");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await expect(page.getByRole("heading", { name: "Launch readiness", level: 1 })).toBeVisible();
  const initiativeUrl = page.url();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Description").fill("Resolve and preserve the release direction.");
  await page.getByRole("button", { name: "Save Initiative" }).click();
  await expect(page.getByText("Resolve and preserve the release direction.")).toBeVisible();
  await page.getByRole("button", { name: "Start an Ask" }).click();
  await expect(page.getByRole("heading", { name: "Shape the Ask." })).toBeVisible();

  await page.getByLabel("Ask title").fill("Choose the release cohort");
  await page.getByLabel("Framing for stakeholders").fill("We need a clear release cohort before launch.");
  await page.getByLabel("Deadline").fill("2026-09-30");
  await page.getByRole("button", { name: "Save details" }).click();
  await page.getByLabel("Question format").selectOption("quantity");
  await page.getByLabel("Question prompt").fill("How many pilot customers should receive the release?");
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.getByRole("heading", { name: "How many pilot customers should receive the release?" })).toBeVisible();
  await page.getByLabel("Question format").selectOption("multi_pick");
  await page.getByLabel("Question prompt").fill("Which release channels should we use?");
  await page.getByLabel("Option 1 value").fill("email");
  await page.getByLabel("Option 1 label").fill("Email");
  await page.getByLabel("Option 2 value").fill("in_app");
  await page.getByLabel("Option 2 label").fill("In-app");
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.getByRole("heading", { name: "Which release channels should we use?" })).toBeVisible();
  await page.getByLabel("Question format").selectOption("when");
  await page.getByLabel("Question prompt").fill("When should the pilot release begin?");
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.getByRole("heading", { name: "When should the pilot release begin?" })).toBeVisible();

  await page.getByLabel("Stakeholder name").fill("Matt");
  await page.getByLabel("Stakeholder email").fill("matt@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  await expect(page.getByText("Matt", { exact: true })).toBeVisible();
  await page.getByLabel("Stakeholder name").fill("April");
  await page.getByLabel("Stakeholder email").fill("april@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  await expect(page.getByText("April", { exact: true })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  await expect(page.getByRole("heading", { name: "Share each personal invitation." })).toBeVisible();
  const mattCopy = await page.getByLabel("Share copy for Matt").inputValue();
  const aprilCopy = await page.getByLabel("Share copy for April").inputValue();
  const mattUrl = extractInvitationUrl(mattCopy);
  const aprilUrl = extractInvitationUrl(aprilCopy);
  await page.getByLabel("Mark Matt sent").evaluate((element: HTMLInputElement) => element.click());
  await expect(page.getByLabel("Mark Matt sent")).toBeChecked();
  await page.getByLabel("Mark April sent").evaluate((element: HTMLInputElement) => element.click());
  await expect(page.getByLabel("Mark April sent")).toBeChecked();

  await page.getByRole("button", { name: "Edit How many pilot customers should receive the release?" }).click();
  await page.getByRole("textbox", { name: "Edit How many pilot customers should receive the release?" }).fill("How many active pilot customers should receive the release?");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save Question" }).click();
  await expect(page.getByRole("heading", { name: "How many active pilot customers should receive the release?" })).toBeVisible();

  const respondent = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const respondentPage = await respondent.newPage();
  await respondentPage.goto(mattUrl);
  await expect(respondentPage.getByRole("heading", { name: "Choose the release cohort" })).toBeVisible();
  await expect(respondentPage.getByText("0 of 3 questions answered.")).toBeVisible();
  const numberQuestion = respondentPage.locator(".question", { hasText: "How many active pilot customers" });
  await expect(numberQuestion.getByLabel("Your answer")).toHaveAttribute("type", "number");
  await numberQuestion.getByLabel("Your answer").fill("1250");
  await numberQuestion.getByLabel("Comment or delegation recommendation").fill("Capacity signal from the pilot roster.");
  await numberQuestion.getByRole("button", { name: "Save answer" }).click();
  await expect(respondentPage.getByText("1 of 3 questions answered.")).toBeVisible();
  const channelQuestion = respondentPage.locator(".question", { hasText: "Which release channels" });
  await channelQuestion.getByLabel("Email", { exact: true }).check();
  await channelQuestion.getByLabel("In-app").check();
  await channelQuestion.getByRole("button", { name: "Save answer" }).click();
  await expect(respondentPage.getByText("2 of 3 questions answered.")).toBeVisible();
  const dateQuestion = respondentPage.locator(".question", { hasText: "When should the pilot release begin" });
  await expect(dateQuestion.getByLabel("Your answer")).toHaveAttribute("type", "date");
  await dateQuestion.getByLabel("Your answer").fill("2026-09-15");
  await dateQuestion.getByRole("button", { name: "Save answer" }).click();
  await expect(respondentPage.getByText("All assigned questions are complete.", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Edit Which release channels should we use?" }).click();
  await page.getByRole("textbox", { name: "Edit Which release channels should we use?" }).fill("Which launch channels should we use?");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save Question" }).click();
  await expect(page.getByRole("heading", { name: "Which launch channels should we use?" })).toBeVisible();
  await respondentPage.reload();
  await expect(respondentPage.getByText("Corrected Question")).toBeVisible();
  const correctedChannel = respondentPage.locator(".question", { hasText: "Which launch channels" });
  await correctedChannel.getByLabel("Email", { exact: true }).check();
  await correctedChannel.getByLabel("In-app").check();
  await correctedChannel.getByRole("button", { name: "Save answer" }).click();
  expect(await respondentPage.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const reopenedRespondent = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const reopenedPage = await reopenedRespondent.newPage();
  await reopenedPage.goto(mattUrl);
  await expect(reopenedPage.getByRole("heading", { name: "Choose the release cohort" })).toBeVisible();
  await reopenedRespondent.close();
  const isolated = await respondentPage.request.get("/api/projects");
  expect(isolated.status()).toBe(401);

  const pendingRespondent = await browser.newContext({ javaScriptEnabled: false });
  const pendingPage = await pendingRespondent.newPage();
  await pendingPage.goto(aprilUrl);
  await expect(pendingPage.getByText("0 of 3 questions answered.")).toBeVisible();

  await page.getByRole("link", { name: "View live results" }).click();
  await expect(page.getByText("1250", { exact: true })).toBeVisible();
  await expect(page.getByText("Unanswered · pending")).toHaveCount(3);
  const numberResult = page.locator(".result-question", { hasText: "How many active pilot customers" });
  await numberResult.getByLabel("Canonical statement").fill("Release to 1,250 active pilot customers.");
  await numberResult.getByLabel("Structured outcome").fill("1250");
  await numberResult.getByLabel("Outcome effect").selectOption("clarified");
  await numberResult.getByLabel("What changed or became clearer?").fill("The initial cohort size is now explicit.");
  await numberResult.getByLabel("Share this outcome with recipients").check();
  await numberResult.getByRole("button", { name: "Commit Decision" }).click();
  const channelResult = page.locator(".result-question", { hasText: "Which launch channels" });
  await channelResult.getByLabel("Canonical statement").fill("Use email and in-app release channels.");
  await channelResult.getByRole("checkbox", { name: "Email", exact: true }).check();
  await channelResult.getByRole("checkbox", { name: "In-app", exact: true }).check();
  await channelResult.getByLabel("Share this outcome with recipients").check();
  await channelResult.getByRole("button", { name: "Commit Decision" }).click();
  const dateResult = page.locator(".result-question", { hasText: "When should the pilot release begin" });
  await expect(dateResult.getByText("Sep 15, 2026")).toBeVisible();
  await dateResult.getByLabel("Canonical statement").fill("Begin the pilot release on September 15, 2026.");
  await dateResult.getByLabel("Structured outcome").fill("2026-09-15");
  await dateResult.getByLabel("Share this outcome with recipients").check();
  await dateResult.getByRole("button", { name: "Commit Decision" }).click();
  await expect(page.getByText("Use email and in-app release channels.")).toBeVisible();
  await expect(page.locator(".draft-state")).toHaveText("closed");

  const projectId = new URL(initiativeUrl).pathname.split("/")[2];
  await page.goto(`/p/${projectId}/feed`);
  await page.getByLabel("Search project memory").fill("capacity signal");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("Capacity signal from the pilot roster.", { exact: false })).toBeVisible();
  await page.getByLabel("Search project memory").fill("Email");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.locator(".feed-result", { hasText: "option" })).toHaveCount(2);
  await page.getByLabel("Search project memory").fill("Release to 1,250 active pilot customers");
  await page.getByRole("button", { name: "Search" }).click();
  const decisionHit = page.locator(".feed-result", { hasText: "Release to 1,250 active pilot customers" });
  await expect(decisionHit).toBeVisible();
  const exportUrl = await decisionHit.getByRole("link", { name: "Export Markdown" }).getAttribute("href");
  expect(exportUrl).not.toBeNull();
  const exported = await page.request.get(exportUrl!);
  expect(exported.status()).toBe(200);
  expect(await exported.text()).toContain("# Decision: Choose the release cohort");

  await pendingPage.reload();
  await expect(pendingPage.getByText("Shared outcome")).toHaveCount(3);
  await expect(pendingPage.getByText("This Question is closed and responses are read only.")).toHaveCount(3);

  await page.goto(initiativeUrl);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Archive" }).click();
  await expect(page.getByText("Archived · read only")).toBeVisible();
  await page.getByRole("button", { name: "Reactivate" }).click();
  await expect(page.getByRole("button", { name: "Archive" })).toBeVisible();
  await respondent.close();
  await pendingRespondent.close();
});

function extractInvitationUrl(message: string) {
  const value = message.match(/https?:\/\/\S+/)?.[0];
  if (!value) throw new Error("Invitation URL missing from share copy");
  return value;
}
