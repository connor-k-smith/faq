import { expect, type Page } from "@playwright/test";

export async function signIn(page: Page, displayName = "Browser Admin", email = "browser-admin@example.com") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Display name").fill(displayName);
  await page.getByRole("button", { name: "Continue with test identity" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}
