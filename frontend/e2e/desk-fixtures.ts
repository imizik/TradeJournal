import { expect, type Page } from "@playwright/test";

/** Opens the thread list's drawer from the top bar's Threads button once the desk has rendered (every width; a phone
 * keeps it in the top row's More). */
export async function openDeskThreads(page: Page) {
  const more = page.getByTestId("desk-top-more");
  await expect(more.or(page.getByRole("button", { name: /^Threads(?:,|$)/ })).first(), "The rendered desk should expose its Threads button").toBeVisible();
  if (await more.isVisible()) {
    if (await page.getByRole("navigation", { name: "Thread list" }).isVisible()) return;
    await more.click();
    await page.getByRole("menuitem", { name: "Threads and previous days" }).click();
    await expect(page.getByRole("navigation", { name: "Thread list" })).toBeVisible();
    return;
  }
  const button = page.getByRole("button", { name: /^Threads(?:,|$)/ });
  await expect(button, "The rendered desk should expose its Threads button").toBeVisible();
  if (await button.getAttribute("aria-pressed") !== "true") await button.click();
  await expect(page.getByRole("navigation", { name: "Thread list" })).toBeVisible();
}
