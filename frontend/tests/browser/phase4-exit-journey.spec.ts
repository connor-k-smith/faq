import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("Phase 4.3 sent Ask expansion and correction successor exit journey", async ({ browser, page }) => {
  test.setTimeout(90_000);

  await signIn(page);

  await page.goto("/organization");
  await page.getByLabel("Project name").fill("Phase 4.3 Exit Project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const project = page.locator(".project-access-card", { hasText: "Phase 4.3 Exit Project" });
  await project.getByLabel("New member for Phase 4.3 Exit Project").selectOption({ label: "Browser Admin" });
  await project.getByLabel("Project role for Phase 4.3 Exit Project").fill("Owner");
  await project.getByRole("button", { name: "Grant access" }).click();
  await expect(project.getByText("Browser Admin", { exact: true })).toBeVisible();

  await page.goto("/");
  await page.getByLabel("Project", { exact: true }).selectOption({ label: "Phase 4.3 Exit Project" });
  await page.getByRole("button", { name: "+ New Initiative" }).click();
  await page.getByLabel("Name").fill("Deterministic closure");
  await page.getByRole("button", { name: "Create Initiative" }).click();
  await page.getByRole("button", { name: "Start an Ask" }).click();
  await page.getByLabel("Ask title").fill("Set the rollout boundary");
  await page.getByLabel("Framing for stakeholders").fill("Capture the current boundary and its correction history.");
  await page.getByRole("button", { name: "Save details" }).click();
  await page.getByLabel("Question format").selectOption("approval");
  await page.getByLabel("Question prompt").fill("Should the rollout include the beta cohort?");
  await page.getByRole("button", { name: "Add Question" }).click();
  await page.getByLabel("Stakeholder name").fill("Original Reviewer");
  await page.getByLabel("Stakeholder email").fill("original@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Prepare to send" }).click();
  const originalUrl = extractInvitationUrl(await page.getByLabel("Share copy for Original Reviewer").inputValue());
  const originalAskUrl = page.url().replace(/\/edit$/, "");
  const originalAsk = await (await page.request.get(new URL(originalAskUrl).pathname.replace("/a/", "/api/asks/"))).json();

  await page.getByLabel("Question format").selectOption("open_question");
  await page.getByLabel("Question prompt").fill("What guardrail should accompany the beta rollout?");
  await page.getByRole("button", { name: "Add Question" }).click();
  const expandedOriginalAsk = await (await page.request.get(new URL(originalAskUrl).pathname.replace("/a/", "/api/asks/"))).json();
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "faq_csrf")!.value;
  const addOwnerRecipient = await page.request.post(`${new URL(originalAskUrl).pathname.replace("/a/", "/api/asks/")}/recipients`, {
    headers: { "X-CSRF-Token": csrf },
    data: {
      actor_id: originalAsk.owner_id,
      question_ids: expandedOriginalAsk.questions.map((question: { id: string }) => question.id),
    },
  });
  expect(addOwnerRecipient.ok()).toBeTruthy();

  const original = await browser.newContext({ javaScriptEnabled: false });
  const originalPage = await original.newPage();
  await originalPage.goto(originalUrl);
  await expect(originalPage.getByText("Should the rollout include the beta cohort?", { exact: true })).toBeVisible();
  await expect(originalPage.getByText("What guardrail should accompany the beta rollout?", { exact: true })).toBeVisible();

  const recipientForm = page.locator(".recipient-form");
  await recipientForm.getByRole("checkbox", { name: "Should the rollout include the beta cohort?" }).uncheck();
  await recipientForm.getByRole("checkbox", { name: "What guardrail should accompany the beta rollout?" }).check();
  await page.getByLabel("Stakeholder name").fill("Guardrail Reviewer");
  await page.getByLabel("Stakeholder email").fill("guardrail@example.com");
  await page.getByRole("button", { name: "Add stakeholder" }).click();
  const guardrailUrl = extractInvitationUrl(await page.getByLabel("Share copy for Guardrail Reviewer").inputValue());
  expect(guardrailUrl).not.toBe(originalUrl);
  await page.reload();
  await expect(page.getByLabel("Share copy for Guardrail Reviewer")).toHaveCount(0);

  const guardrail = await browser.newContext({ javaScriptEnabled: false });
  const guardrailPage = await guardrail.newPage();
  await guardrailPage.goto(guardrailUrl);
  await expect(guardrailPage.getByText("Should the rollout include the beta cohort?", { exact: true })).toHaveCount(0);
  const guardrailQuestion = guardrailPage.locator(".question", { hasText: "What guardrail should accompany" });
  await guardrailQuestion.getByLabel("Your answer").fill("Require an opt-out control.");
  await guardrailQuestion.getByRole("button", { name: "Save answer" }).click();
  expect((await guardrailPage.request.get("/api/projects")).status()).toBe(401);

  await page.goto(originalAskUrl);
  const originalResult = page.locator(".result-question", { hasText: "Should the rollout include the beta cohort?" });
  await originalResult.getByLabel("Canonical statement").fill("Include the beta cohort in the rollout.");
  await originalResult.getByLabel("Structured outcome").selectOption("yes");
  await originalResult.getByLabel("Outcome effect").selectOption("clarified");
  await originalResult.getByLabel("What changed or became clearer?").fill("The included cohort is explicit.");
  await originalResult.getByRole("button", { name: "Commit Decision" }).click();
  const guardrailResult = page.locator(".result-question", { hasText: "What guardrail should accompany" });
  await guardrailResult.getByLabel("Canonical statement").fill("Require an opt-out control for the beta cohort.");
  await guardrailResult.getByRole("button", { name: "Commit Decision" }).click();
  await expect(page.locator(".draft-state")).toHaveText("closed");

  const priorResults = await (await page.request.get(`${new URL(originalAskUrl).pathname.replace("/a/", "/api/asks/")}/results`)).json();
  const priorDecisionId = priorResults.questions.find((question: { prompt: string }) => question.prompt.startsWith("Should"))!.decision.id;
  await originalResult.getByRole("button", { name: "Create correction successor" }).click();
  await expect(page).toHaveURL(/\/a\/[^/]+\/edit$/);
  const successorAskUrl = page.url().replace(/\/edit$/, "");
  await expect(page.getByRole("heading", { name: "Should the rollout include the beta cohort?" })).toBeVisible();
  const successorApiUrl = new URL(successorAskUrl).pathname.replace("/a/", "/api/asks/");
  const addExistingRecipient = await page.request.post(`${successorApiUrl}/recipients`, {
    headers: { "X-CSRF-Token": csrf },
    data: { actor_id: originalAsk.owner_id },
  });
  expect(addExistingRecipient.ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText(/0 open · 1 assignment across 1 Ask in the last 7 days/)).toBeVisible();
  await page.getByRole("button", { name: "Prepare to send" }).click();
  await expect(page.getByRole("alert")).toContainText("Browser Admin has existing or recent assignments");
  await expect(page.getByRole("heading", { name: "Share each personal invitation." })).toHaveCount(0);
  await page.getByRole("button", { name: "Send anyway" }).click();
  const successorUrl = extractInvitationUrl(await page.getByLabel("Share copy for Browser Admin").inputValue());

  const successor = await browser.newContext({ javaScriptEnabled: false });
  const successorPage = await successor.newPage();
  await successorPage.goto(successorUrl);
  const successorQuestion = successorPage.locator(".question", { hasText: "Should the rollout include" });
  await successorQuestion.getByRole("radio", { name: "No", exact: true }).check();
  await successorQuestion.getByRole("button", { name: "Save answer" }).click();

  await page.goto(successorAskUrl);
  const successorResult = page.locator(".result-question", { hasText: "Should the rollout include" });
  await successorResult.getByLabel("Canonical statement").fill("Exclude the beta cohort from the rollout.");
  await successorResult.getByLabel("Structured outcome").selectOption("no");
  await successorResult.getByLabel("Outcome effect").selectOption("changed");
  await successorResult.getByLabel("What changed or became clearer?").fill("The beta cohort is now excluded.");
  await successorResult.getByRole("button", { name: "Commit Decision" }).click();
  await expect(page.locator(".draft-state")).toHaveText("closed");

  const successorResults = await (await page.request.get(`${new URL(successorAskUrl).pathname.replace("/a/", "/api/asks/")}/results`)).json();
  expect(successorResults.questions[0].decision.supersedes_decision_id).toBe(priorDecisionId);
  await page.goto(originalAskUrl);
  await expect(page.locator(".draft-state")).toHaveText("closed");
  await expect(originalResult.getByText("Historical Decision · superseded")).toBeVisible();
  const currentDecisionLink = originalResult.getByRole("link", { name: "Export current Decision" });
  await expect(currentDecisionLink).toHaveAttribute("href", `/d/${successorResults.questions[0].decision.id}.md`);
  await expect(originalResult.getByText("Include the beta cohort in the rollout.", { exact: true })).toBeVisible();

  await original.close();
  await guardrail.close();
  await successor.close();
});

function extractInvitationUrl(message: string) {
  const value = message.match(/https?:\/\/\S+/)?.[0];
  if (!value) throw new Error("Invitation URL missing from share copy");
  return value;
}
