import { expect, test, type Page } from "@playwright/test";
import { speechText, type Proposal } from "../lib/copilot";

// Read it back: the copilot's answer spoken by the browser's own speech synthesis. The lab routes are stubbed in the
// browser (the e2e backend keeps the lab off); speech synthesis, the microphone and the recorder are fakes that log
// what they were asked to do, so nothing speaks or records.

const PLAN: Proposal = { id: "p1", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "calls", contract: "NBIS 95C",
  thesis: "Holds the high", entry_trigger: { condition: "crosses", price: 101.5, interval: "15m" },
  invalidation: { condition: "closes_beyond", price: 98, interval: "15m" }, time_stop: null, size_note: null };
const WATCH: Proposal = { id: "w1", kind: "watch", symbol: "NBIS", condition: "touches", price: 98, interval: null, label: "NBIS 98", why: "Stop" };

test.describe("what is spoken", () => {
  test("markdown, lists, tickers, prices and the simulated head", () => {
    const content = "_(Simulated model — scripted text from the tool results, not Claude.)_\n\n"
      + "## Read\n**NBIS** is above its 15-minute high at $101.50, up +3.2% on the day.\n\n"
      + "- Group: CRWV and APLD confirm\n- Stop below $98\n1. Size 1,200 shares, risk ~$450 → 2.5R";
    expect(speechText({ content })).toBe("Read. N B I S is above its 15-minute high at 101 dollars and 50 cents, up 3.2 percent on the day. "
      + "Group: C R W V and A P L D confirm. Stop below 98 dollars. Size 1200 shares, risk about 450 dollars to 2.5 R.");
  });

  test("the answer format's Read and Against lines", () => {
    const content = "Verdict: Wait — Not yet.\n\nRead: Thesis holds · Timing early · Contract mismatch\n\nThe group leads.\n\nAgainst: CRWV is fading.";
    expect(speechText({ content })).toBe("Wait. Not yet. Thesis holds, Timing early, Contract mismatch. The group leads. Against that, C R W V is fading.");
  });

  test("a compare block reads each row as its two sides", () => {
    const content = "Verdict: Unclear — A coin flip.\n\nCompare: enter now | wait for 95.9\nNeeds: the group to hold | a reclaim on volume\n"
      + "Risks: being early | missing it\n\nAgainst: CRWV is fading.";
    expect(speechText({ content })).toBe("Unclear. A coin flip. Compare A, enter now, and B, wait for 95.9. "
      + "Needs: A, the group to hold; B, a reclaim on volume. Risks: A, being early; B, missing it. Against that, C R W V is fading.");
  });

  test("option contracts, ranges, cents, losses, links and code", () => {
    expect(speechText({ content: "Buy the `NBIS 95C` if it holds $100–$102. Premium $0.85; P&L -$1,234 on $2.5M. See [the news](https://example.com/a). Earnings 2026-10-29." }))
      .toBe("Buy the N B I S 95 call if it holds 100 dollars to 102 dollars. Premium 85 cents; P and L minus 1234 dollars on 2.5 million dollars. See the news. Earnings October 29, 2026.");
  });

  test("cards close with one sentence; an empty answer says its error; a stopped one says nothing", () => {
    expect(speechText({ content: "Plan drafted.", proposals: [PLAN] })).toBe("Plan drafted. There is a plan card to confirm.");
    expect(speechText({ content: "Two.", proposals: [WATCH, { ...WATCH, id: "w2" }] })).toBe("Two. There are 2 watch cards to confirm.");
    expect(speechText({ content: "Both.", proposals: [PLAN, WATCH] })).toBe("Both. There are 2 cards to confirm.");
    expect(speechText({ content: "", error: { code: "network", message: "Copilot Lab could not be reached." } })).toBe("Copilot Lab could not be reached.");
    expect(speechText({ content: "", error: { code: "stopped", message: "Stopped." } })).toBe("");
  });
});

const status = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true, transcriber: { configured: true, provider: "Whisper base.en (on this server)" } },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const ANSWER = "_(Simulated model — scripted text from the tool results, not Claude.)_\n\n**NBIS** holds $101.50.\n\n- Group confirms";
const SPOKEN = "N B I S holds 101 dollars and 50 cents. Group confirms. There is a plan card to confirm.";
const frames = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const TURN = frames([
  ...ANSWER.split(/(?<= )/).map((delta) => ({ type: "text", delta })),
  { type: "proposal", ...PLAN },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

type Said = { text: string; rate: number; lang: string; voice: string | null };
const log = (page: Page) => page.evaluate(() => (window as unknown as { __speech: string[] }).__speech);
const said = (page: Page) => page.evaluate(() => (window as unknown as { __said: Said[] }).__said.filter((s) => s.text.trim()));

async function lab(page: Page, { speech = true } = {}) {
  await page.addInitScript((supported: boolean) => {
    const w = window as unknown as Record<string, unknown>;
    const events: string[] = [];
    const heard: { text: string; rate: number; lang: string; voice: string | null }[] = [];
    w.__speech = events;
    w.__said = heard;
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {
      getUserMedia: () => { events.push("microphone"); return Promise.resolve({ getTracks: () => [{ stop() {} }] }); },
    } });
    w.MediaRecorder = class {
      static isTypeSupported(type: string) { return type === "audio/webm;codecs=opus"; }
      state = "inactive"; mimeType = "audio/webm;codecs=opus";
      ondataavailable: ((event: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob([new Uint8Array(4000)], { type: this.mimeType }) });
        setTimeout(() => this.onstop?.(), 0);
      }
    };
    delete w.SpeechRecognition;
    delete w.webkitSpeechRecognition;
    if (!supported) {
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: undefined });
      Object.defineProperty(window, "SpeechSynthesisUtterance", { configurable: true, value: undefined });
      return;
    }
    // An utterance keeps "speaking" until it is cancelled, so a stop is always observable.
    type Utterance = { text: string; rate: number; lang: string; volume: number; voice: { name: string } | null; onend: (() => void) | null; onerror: ((e: unknown) => void) | null };
    let current: Utterance | null = null;
    Object.defineProperty(window, "SpeechSynthesisUtterance", { configurable: true, value: class {
      rate = 1; lang = ""; volume = 1; voice = null; onend = null; onerror = null;
      constructor(public text: string) {}
    } });
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
      get speaking() { return current !== null; }, pending: false,
      getVoices: () => [{ name: "Thomas", lang: "fr-FR", default: true }, { name: "Samantha", lang: "en-US", default: false }],
      speak(u: Utterance) { events.push(u.text.trim() ? "speak" : "prime"); heard.push({ text: u.text, rate: u.rate, lang: u.lang, voice: u.voice?.name ?? null }); current = u; },
      cancel() { events.push("cancel"); const u = current; current = null; u?.onerror?.({ error: "canceled" }); },
    } });
  }, speech);
  const chats: { messages: { content: string }[] }[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: {
    as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "closed", need_you: 0, streak: null }, sections: {}, threads: [] } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: {
    id: "33333333-3333-4333-8333-333333333333", source: "copilot", title: "x", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
    message_count: 2, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:05:00Z", transcript: [], evidence: [], findings: null } }));
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: {} }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/plans*", (route) => route.fulfill({ json: { plans: [] } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/chat", (route) => {
    chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  await page.route("**/copilot/transcribe", (route) => route.fulfill({ json: { text: "What about NBIS now", heard: "what about en bis now", tickers: [], provider: "Whisper" } }));
  return chats;
}

const speaker = (page: Page) => page.getByTestId("copilot-speak");
const box = (page: Page) => page.getByRole("textbox", { name: "Message", exact: true });

async function ask(page: Page, text: string) {
  await box(page).fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

test("the speaker is remembered; each answer is spoken once, after it finishes, at the chosen speed", async ({ page }) => {
  await lab(page);
  await page.goto("/copilot-lab");
  await expect(speaker(page)).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByLabel("Voice speed")).toHaveCount(0);
  await speaker(page).click();
  await expect(speaker(page)).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(speaker(page)).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => localStorage.getItem("copilot.speak"))).toBe("on");
  await page.getByLabel("Voice speed").selectOption("1.2");

  await ask(page, "Is NBIS holding?");
  await expect(speaker(page)).toHaveAttribute("aria-label", "Stop reading aloud");
  expect(await said(page)).toEqual([{ text: SPOKEN, rate: 1.2, lang: "en-US", voice: "Samantha" }]);

  // A new turn stops the answer being read before the next one is spoken.
  await ask(page, "And the group?");
  await expect.poll(async () => (await said(page)).length).toBe(2);
  const events = (await log(page)).filter((e) => e !== "prime");
  expect(events.lastIndexOf("cancel")).toBeGreaterThan(events.indexOf("speak"));
  expect(events.lastIndexOf("cancel")).toBeLessThan(events.lastIndexOf("speak"));

  // A tap on the speaker while it reads stops it and leaves it on.
  await speaker(page).click();
  await expect(speaker(page)).toHaveAttribute("aria-label", "Read answers aloud");
  await expect(speaker(page)).toHaveAttribute("aria-pressed", "true");
  expect((await log(page)).at(-1)).toBe("cancel");
});

test("hands-free: pressing the mic stops speech before it listens, and the spoken question's answer is read", async ({ page }) => {
  const chats = await lab(page);
  await page.goto("/copilot-lab");
  await speaker(page).click();
  await ask(page, "Is NBIS holding?");
  await expect(speaker(page)).toHaveAttribute("aria-label", "Stop reading aloud");

  const mic = page.getByTestId("copilot-mic");
  await mic.hover();
  await page.mouse.down();
  await expect(page.getByTestId("copilot-voice-status")).toContainText("release to transcribe");
  const events = await log(page);
  expect(events.indexOf("microphone")).toBeGreaterThan(events.lastIndexOf("speak"));
  expect(events.slice(events.lastIndexOf("speak"), events.indexOf("microphone"))).toContain("cancel");
  await page.waitForTimeout(600);
  await page.mouse.up();

  await expect.poll(() => chats.length).toBe(2);
  expect(chats[1].messages.at(-1)!.content).toBe("What about NBIS now");
  await expect.poll(async () => (await said(page)).length).toBe(2);
  await expect(page.getByTestId("copilot-mic")).toBeEnabled();
});

test("a hidden page stops speaking", async ({ page }) => {
  await lab(page);
  await page.goto("/copilot-lab");
  await speaker(page).click();
  await ask(page, "Is NBIS holding?");
  await expect(speaker(page)).toHaveAttribute("aria-label", "Stop reading aloud");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(speaker(page)).toHaveAttribute("aria-label", "Read answers aloud");
  expect((await log(page)).at(-1)).toBe("cancel");
});

test("without speech synthesis there is no speaker", async ({ page }) => {
  await lab(page, { speech: false });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("copilot-mic")).toBeVisible();
  await expect(speaker(page)).toHaveCount(0);
  await expect(page.getByLabel("Voice speed")).toHaveCount(0);
});

test("at 375 px the speaker waits behind + on the mic's row, the box takes the full width, and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page);
  await page.goto("/copilot-lab");
  await expect(page.getByText("Nothing open. Plan a trade to start a ticker.")).toBeVisible();
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click(); // a phone shows the conversation on its own tab
  await expect(speaker(page)).toBeHidden(); // attach and read-aloud wait behind "+"
  await page.getByRole("button", { name: "More: attach, read aloud" }).click();
  await speaker(page).click();
  const target = (await speaker(page).boundingBox())!;
  const mic = (await page.getByTestId("copilot-mic").boundingBox())!;
  expect(target.width).toBeGreaterThanOrEqual(44);
  expect(target.height).toBeGreaterThanOrEqual(44);
  expect(target.x + target.width).toBeLessThanOrEqual(375);
  expect(Math.abs(target.y + target.height / 2 - (mic.y + mic.height / 2))).toBeLessThan(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  // The text field gets the full width; the buttons sit on their own row under it.
  const field = (await box(page).boundingBox())!;
  expect(field.width).toBeGreaterThanOrEqual(300);
  expect(target.y).toBeGreaterThanOrEqual(field.y + field.height);
  if (process.env.SPEAK_SHOT) await page.screenshot({ path: process.env.SPEAK_SHOT });
});
