import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("unanimous approval settles lazily and auto-commits before owner completion", async ({ browser, page }) => {
  test.setTimeout(135_000);

  await signIn(page);

  await page.goto("/organization");
  await page.getByLabel("Project name").fill("Automatic Resolution Project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const project = page.locator(".project-access-card", { hasText: "Automatic Resolution Project" });
  await project.getByLabel("New member for Automatic Resolution Project").selectOption({ label: "Browser Admin" });
  await project.getByLabel("Project role for Automatic Resolution Project").fill("Owner");
  await project.getByRole("button", { name: "Grant access" }).click();

  await page.goto("/");
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Release authorization");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await page.getByRole("button", { name: "Start an Ask" }).click();
  await page.getByLabel("Ask title").fill("Authorize the release");
  await page.getByLabel("Framing for stakeholders").fill("Confirm the release can proceed.");
  await page.getByRole("button", { name: "Save details" }).click();
  await page.getByLabel("Question format").selectOption("approval");
  await page.getByLabel("Question prompt").fill("Should we authorize the release?");
  await page.getByRole("button", { name: "Add Question" }).click();

  for (const [name, email] of [["Riley", "riley@example.com"], ["Morgan", "morgan@example.com"]]) {
    await page.getByLabel("Stakeholder name").fill(name);
    await page.getByLabel("Stakeholder email").fill(email);
    await page.getByRole("button", { name: "Add stakeholder" }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  const invitationUrls = await Promise.all(["Riley", "Morgan"].map(async (name) => {
    const copy = await page.getByLabel(`Share copy for ${name}`).inputValue();
    const url = copy.match(/https?:\/\/\S+/)?.[0];
    if (!url) throw new Error(`Invitation URL missing for ${name}`);
    return url;
  }));

  for (const invitationUrl of invitationUrls) {
    const respondent = await browser.newContext({ javaScriptEnabled: false });
    const responsePage = await respondent.newPage();
    await responsePage.goto(invitationUrl);
    const question = responsePage.locator(".question", { hasText: "Should we authorize the release?" });
    await question.getByRole("radio", { name: "Yes", exact: true }).check();
    await question.getByRole("button", { name: "Save answer" }).click();
    await expect(question.getByText("Saved response, version 1")).toBeVisible();
    if (invitationUrl === invitationUrls[1]) {
      await expect(question.getByText("You can revise until", { exact: false })).toBeVisible();
    }
    await respondent.close();
  }

  // No results read occurs during the one-minute deployment grace; this navigation settles it lazily.
  await page.waitForTimeout(62_000);
  await page.getByRole("link", { name: "View live results" }).click();
  const result = page.locator(".result-question", { hasText: "Should we authorize the release?" });
  await expect(result.getByText("Auto-committed · awaiting outcome effect")).toBeVisible();
  await expect(result.getByText("Computed value: yes")).toBeVisible();
  await expect(result.getByText("2 substantive / 2 eligible")).toBeVisible();
  await expect(result.getByRole("heading", { name: "Record the outcome effect to complete" })).toBeVisible();

  await result.getByLabel("Outcome effect").selectOption("clarified");
  await result.getByLabel("Effect note").fill("Both stakeholders confirmed release authorization.");
  await result.getByRole("button", { name: "Record outcome effect" }).click();
  await expect(result.getByText("Canonical Decision · complete")).toBeVisible();
  await expect(page.locator(".draft-state")).toHaveText("closed");
});
