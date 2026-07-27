import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("Phase 4.1 advisory input never determines or reopens a Decision", async ({ browser, page }) => {
  test.setTimeout(90_000);

  await signIn(page);

  await page.goto("/organization");
  await page.getByLabel("Invite by email").fill("phase4-member@example.com");
  await page.getByRole("button", { name: "Invite" }).click();
  await expect(page.getByText("phase4-member@example.com", { exact: true })).toBeVisible();
  await page.getByLabel("Project name").fill("Phase 4 Advisory Project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const project = page.locator(".project-access-card", { hasText: "Phase 4 Advisory Project" });
  await project.getByLabel("New member for Phase 4 Advisory Project").selectOption({ label: "Browser Admin" });
  await project.getByRole("button", { name: "Grant access" }).click();

  const member = await browser.newContext();
  const memberPage = await member.newPage();
  await signIn(memberPage, "Advisory Member", "phase4-member@example.com");

  await page.reload();
  await project.getByLabel("New member for Phase 4 Advisory Project").selectOption({ label: "Advisory Member" });
  await project.getByLabel("Project role for Phase 4 Advisory Project").fill("Member");
  await project.getByRole("button", { name: "Grant access" }).click();

  await page.goto("/");
  await page.getByLabel("Project", { exact: true }).selectOption({ label: "Phase 4 Advisory Project" });
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Advisory exit gate");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await page.getByRole("button", { name: "Start an Ask" }).click();
  await page.getByLabel("Ask title").fill("Choose the launch posture");
  await page.getByLabel("Framing for stakeholders").fill("Assigned input determines the committed posture.");
  await page.getByRole("button", { name: "Save details" }).click();
  await page.getByLabel("Question format").selectOption("approval");
  await page.getByLabel("Question prompt").fill("Should we launch now?");
  await page.getByLabel("Who may contribute").selectOption("project_members");
  await page.getByRole("button", { name: "Add Question" }).click();
  await expect(page.locator("small", { hasText: "Project members may advise" })).toBeVisible();
  await page.getByLabel("Stakeholder name").fill("Assigned Reviewer");
  await page.getByLabel("Stakeholder email").fill("assigned-reviewer@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  const invitation = await page.getByLabel("Share copy for Assigned Reviewer").inputValue();
  const invitationUrl = invitation.match(/https?:\/\/\S+/)?.[0];
  if (!invitationUrl) throw new Error("Assigned reviewer invitation URL missing");
  const askUrl = new URL(page.url());
  askUrl.pathname = askUrl.pathname.replace(/\/edit$/, "");

  await memberPage.goto(askUrl.toString());
  const memberQuestion = memberPage.locator(".result-question", { hasText: "Should we launch now?" });
  await expect(memberQuestion.getByText("Not assigned to you · you can still weigh in")).toBeVisible();
  await memberQuestion.getByLabel("Advisory response").selectOption("no");
  await memberQuestion.getByLabel("Advisory comment").fill("Advisory Member recommends waiting.");
  await memberQuestion.getByRole("button", { name: "Add advisory response" }).click();
  await expect(memberQuestion.getByText("Advisory Member", { exact: true })).toBeVisible();
  await expect(memberQuestion.getByText("Advisory · not asked directly")).toBeVisible();
  await expect(memberQuestion.locator(".answer-value")).toHaveText("No");

  const assigned = await browser.newContext({ javaScriptEnabled: false });
  const assignedPage = await assigned.newPage();
  await assignedPage.goto(invitationUrl);
  const assignedQuestion = assignedPage.locator(".question", { hasText: "Should we launch now?" });
  await assignedQuestion.getByRole("radio", { name: "Yes", exact: true }).check();
  await assignedQuestion.getByRole("button", { name: "Save answer" }).click();
  await expect(assignedQuestion.getByText("Saved response, version 1")).toBeVisible();

  await page.goto(askUrl.toString());
  const result = page.locator(".result-question", { hasText: "Should we launch now?" });
  await expect(result.getByText("Advisory Member", { exact: true })).toBeVisible();
  await expect(result.getByRole("checkbox", { name: "Assigned Reviewer Determining" })).toBeChecked();
  await expect(result.getByRole("checkbox", { name: /Advisory Member.*Determining/ })).toHaveCount(0);
  await result.getByLabel("Canonical statement").fill("Launch now.");
  await result.getByLabel("Structured outcome").selectOption("yes");
  await result.getByLabel("Outcome effect").selectOption("clarified");
  await result.getByLabel("What changed or became clearer?").fill("The assigned reviewer approved launch.");
  await result.getByRole("button", { name: "Commit Decision" }).click();
  await expect(result.getByText("Launch now.", { exact: true })).toBeVisible();
  await expect(page.locator(".draft-state")).toHaveText("closed");
  const committedResults = await (await page.request.get(`${askUrl.pathname}/results`.replace("/a/", "/api/asks/"))).json();
  const committedDecision = committedResults.questions[0].decision;
  expect(committedDecision.value).toBe("yes");
  expect(committedDecision.substantive_evidence_count).toBe(1);
  expect(committedDecision.evidence).toHaveLength(1);

  await memberPage.reload();
  await expect(memberQuestion.getByText("Launch now.", { exact: true })).toBeVisible();
  await memberQuestion.getByLabel("Advisory response").selectOption("yes");
  await memberQuestion.getByLabel("Advisory comment").fill("Late revision after the Decision was committed.");
  await memberQuestion.getByRole("button", { name: "Add late advisory response" }).click();
  await expect(memberQuestion.getByText("Late", { exact: true })).toBeVisible();
  await expect(memberQuestion.getByText("2 revisions")).toBeVisible();
  await expect(memberQuestion.getByText("Launch now.", { exact: true })).toBeVisible();

  await page.reload();
  await expect(result.getByText("Launch now.", { exact: true })).toBeVisible();
  await expect(page.locator(".draft-state")).toHaveText("closed");
  const resultsAfterLateRevision = await (await page.request.get(`${askUrl.pathname}/results`.replace("/a/", "/api/asks/"))).json();
  expect(resultsAfterLateRevision.questions[0].decision).toMatchObject({
    id: committedDecision.id,
    state: "committed",
    value: "yes",
    statement: "Launch now.",
    substantive_evidence_count: 1,
    evidence: committedDecision.evidence,
  });

  await assigned.close();
  await member.close();
});
