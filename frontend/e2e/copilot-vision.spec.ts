import { expect, test, type Page } from "@playwright/test";

// The copilot can see: a screenshot attached from the lab's composer, and one arriving from the phone's share sheet.
// The lab routes are stubbed in the browser (the e2e backend keeps the lab off), so the share route's own request to the
// backend is refused and comes back as a plain note; the route's success path is the backend's test_copilot_images.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
const ID = "0123456789abcdef0123456789abcdef";
const PREFILL = "Here is my chart. What do you see, and what would the plan be?";
const status = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true, transcriber: { configured: false, provider: "none" } },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const TURN = [
  { type: "tool", id: "t1", name: "get_trade_review", status: "ok", summary: "NBIS 100C · plan ok", looked_at: ["plan chart"],
    provenance: { source: "TradeJournal journal", kind: "saved", as_of: null } },
  { type: "text", delta: "I can read a rising line and a red level near 92.50." },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");

type Seen = { chats: { messages: { content: string }[]; image_ids?: string[] }[]; uploads: number; saved: { transcript: { content: string }[] }[] };

async function lab(page: Page): Promise<Seen> {
  const seen: Seen = { chats: [], uploads: 0, saved: [] };
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status }));
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: {
    positions: { state: "ok", count: 0, positions: [] }, investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] }, as_of: null } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => {
    seen.saved.push(route.request().postDataJSON());
    return route.fulfill({ status: 201, json: {
      id: "33333333-3333-4333-8333-333333333333", source: "copilot", title: "x", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
      message_count: 2, has_findings: false, created_at: "2026-10-26T14:00:00Z", updated_at: "2026-10-26T14:05:00Z", transcript: [], evidence: [], findings: null } });
  });
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: {} }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/images", (route) => {
    seen.uploads += 1;
    expect(route.request().postDataBuffer()?.toString("latin1")).toContain('name="image"');
    return route.fulfill({ status: 201, json: { id: `${seen.uploads}`.padStart(32, "a"), width: 1, height: 1, bytes: 600 } });
  });
  await page.route(`**/copilot/images/${ID}`, (route) => route.fulfill({ status: 200, contentType: "image/png", body: PNG }));
  await page.route("**/copilot/chat", (route) => {
    seen.chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  return seen;
}

const box = (page: Page) => page.getByRole("textbox", { name: "Message", exact: true });

test("attach a screenshot: thumbnail, a ready question, the id in the chat body, a text marker in the saved transcript", async ({ page }) => {
  const seen = await lab(page);
  await page.goto("/copilot-lab");
  await expect(page.getByText("No open positions.")).toBeVisible();
  await page.getByTestId("copilot-image-input").setInputFiles({ name: "chart.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByRole("img", { name: "Attached screenshot" })).toBeVisible();
  await expect(box(page)).toHaveValue(PREFILL);
  expect(seen.uploads).toBe(1);

  // Remove, then attach again; a second one may join it, a third may not.
  await page.getByRole("button", { name: "Remove screenshot" }).click();
  await expect(page.getByRole("img", { name: "Attached screenshot" })).toHaveCount(0);
  await page.getByTestId("copilot-image-input").setInputFiles([
    { name: "a.png", mimeType: "image/png", buffer: PNG }, { name: "b.png", mimeType: "image/png", buffer: PNG }]);
  await expect(page.getByRole("img", { name: "Attached screenshot" })).toHaveCount(2);
  await expect(page.getByTestId("copilot-attach")).toBeDisabled();

  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("I can read a rising line")).toBeVisible();
  const body = seen.chats[0];
  expect(body.image_ids).toEqual(["a".repeat(31) + "2", "a".repeat(31) + "3"]);
  expect(body.messages.at(-1)!.content).toBe(`[shared a screenshot] ${PREFILL}`);
  await expect(page.getByRole("img", { name: "Shared screenshot" })).toHaveCount(2);  // on the sent message
  await expect(page.getByRole("img", { name: "Attached screenshot" })).toHaveCount(0);
  await expect(page.getByText("Looked at: plan chart")).toBeVisible();
  await expect.poll(() => seen.saved.length).toBe(1);
  expect(seen.saved[0].transcript[0].content).toBe(`[shared a screenshot] ${PREFILL}`);

  // The next turn sends no image, and history keeps the marker.
  await box(page).fill("And the invalidation?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => seen.chats.length).toBe(2);
  expect(seen.chats[1].image_ids).toBeUndefined();
  expect(seen.chats[1].messages[0].content).toBe(`[shared a screenshot] ${PREFILL}`);
});

test("a screenshot from the share sheet opens the lab with it attached and a question ready, nothing sent", async ({ page }) => {
  const seen = await lab(page);
  await page.goto(`/copilot-lab?image=${ID}&context=${encodeURIComponent("Plan a trade from this screenshot")}`);
  await expect(page.getByRole("img", { name: "Attached screenshot" })).toBeVisible();
  await expect(box(page)).toHaveValue(`Context: Plan a trade from this screenshot\n\n${PREFILL}`);
  expect(seen.chats).toHaveLength(0);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => seen.chats.length).toBe(1);
  expect(seen.chats[0].image_ids).toEqual([ID]);
});

test("the manifest offers the share target, and the share route answers with a redirect to the lab", async ({ request }) => {
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest.share_target).toMatchObject({ action: "/share-target", method: "POST", enctype: "multipart/form-data",
    params: { files: [{ name: "image" }] } });
  const empty = await request.post("/share-target", { multipart: { title: "x" }, maxRedirects: 0 });
  expect(empty.status()).toBe(303);
  expect(empty.headers().location).toContain("/copilot-lab?context=The+share+carried+no+image");
  // The e2e backend keeps the lab off, so storing is refused and the lab opens with a note instead of an image.
  const shared = await request.post("/share-target", { multipart: { image: { name: "chart.png", mimeType: "image/png", buffer: PNG } }, maxRedirects: 0 });
  expect(shared.status()).toBe(303);
  expect(shared.headers().location).toContain("could+not+be+attached");
  expect(shared.headers().location).not.toContain("image=");
});
