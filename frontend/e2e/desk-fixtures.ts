import { expect, type Page } from "@playwright/test";

/** Opens the thread list's drawer from the top bar's Threads button once the desk has rendered (every width). */
export async function openDeskThreads(page: Page) {
  const button = page.getByRole("button", { name: /^Threads(?:,|$)/ });
  await expect(button, "The rendered desk should expose its Threads button").toBeVisible();
  if (await button.getAttribute("aria-pressed") !== "true") await button.click();
  await expect(page.getByRole("navigation", { name: "Thread list" })).toBeVisible();
}
