import { expect, type Page } from "@playwright/test";

/** Opens the normal Threads control once the desk has rendered, using the phone tab on narrow layouts. */
export async function openDeskThreads(page: Page) {
  const desktop = page.getByRole("button", { name: /^Threads(?:,|$)/ });
  const phone = page.getByRole("tab", { name: "Threads", exact: true });
  await expect.poll(async () => (await desktop.isVisible()) || (await phone.isVisible()), {
    message: "The rendered desk should expose its Threads button or phone tab",
  }).toBe(true);

  if (await desktop.isVisible()) {
    if (await desktop.getAttribute("aria-pressed") !== "true") await desktop.click();
  } else if (await phone.getAttribute("aria-selected") !== "true") {
    await phone.click();
  }
  await expect(page.getByRole("navigation", { name: "Thread list" })).toBeVisible();
}
