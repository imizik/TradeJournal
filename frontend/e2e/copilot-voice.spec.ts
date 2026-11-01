import { expect, test, type Page } from "@playwright/test";

// Hold-to-talk in the copilot's composer. The lab routes are stubbed in the browser (the e2e backend keeps the lab
// off); the microphone, MediaRecorder and the browser's speech recognition are fakes, so nothing records or listens.
const status = (configured: boolean) => ({
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true, transcriber: { configured, provider: configured ? "Whisper base.en (on this server)" : "none" } },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
});
const TURN = [
  { type: "text", delta: "NBIS is above its 15-minute high." },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const SPOKEN = "I want NBIS calls if it holds 100";

type Fakes = { denied?: boolean; recognition?: boolean };
type Lab = { chats: { messages: { content: string }[] }[]; transcribes: string[] };

async function lab(page: Page, { configured = true, ...fakes }: Fakes & { configured?: boolean } = {}): Promise<Lab> {
  const seen: Lab = { chats: [], transcribes: [] };
  await page.addInitScript((f: Fakes) => {
    const w = window as unknown as Record<string, unknown>;
    // A microphone that answers at once (or is refused), and a recorder that hands back one small clip.
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {
      getUserMedia: () => f.denied ? Promise.reject(new DOMException("Permission denied", "NotAllowedError"))
        : Promise.resolve({ getTracks: () => [{ stop() {} }] }),
    } });
    class FakeRecorder {
      static isTypeSupported(type: string) { return type === "audio/webm;codecs=opus"; }
      state = "inactive"; mimeType = "audio/webm;codecs=opus";
      ondataavailable: ((event: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob([new Uint8Array(4000)], { type: this.mimeType }) });
        setTimeout(() => this.onstop?.(), 0);
      }
    }
    w.MediaRecorder = FakeRecorder;
    delete w.SpeechRecognition;
    delete w.webkitSpeechRecognition;
    if (f.recognition) {
      w.webkitSpeechRecognition = class {
        lang = ""; continuous = false; interimResults = false;
        onresult: ((event: unknown) => void) | null = null; onerror: ((event: unknown) => void) | null = null;
        onend: (() => void) | null = null; onstart: (() => void) | null = null;
        start() {
          setTimeout(() => f.denied ? (this.onerror?.({ error: "not-allowed" }), this.onend?.()) : this.onstart?.(), 0);
        }
        stop() {
          this.onresult?.({ resultIndex: 0, results: [Object.assign([{ transcript: "en bis over the high" }], { isFinal: true })] });
          setTimeout(() => this.onend?.(), 0);
        }
        abort() { setTimeout(() => this.onend?.(), 0); }
      };
    }
  }, fakes);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status(configured) }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: {
    as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "closed", need_you: 0, streak: null }, sections: {}, threads: [] } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: {
    id: "33333333-3333-4333-8333-333333333333", source: "copilot", title: "x", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
    message_count: 2, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:05:00Z", transcript: [], evidence: [], findings: null } }));
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: {} }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/chat", (route) => {
    seen.chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  await page.route("**/copilot/transcribe", (route) => {
    const body = route.request().postDataBuffer()?.toString("latin1") ?? "";
    seen.transcribes.push(body.includes('name="audio"') ? "audio" : "text");
    if (body.includes('name="text"')) return route.fulfill({ json: { text: "NBIS over the high", heard: "en bis over the high", tickers: [], provider: "browser" } });
    return route.fulfill({ json: { text: SPOKEN, heard: "I want en bis calls if it holds 100", tickers: [{ heard: "en bis", symbol: "NBIS" }], provider: "Whisper" } });
  });
  return seen;
}

async function hold(page: Page, ms = 700) {
  const mic = page.getByTestId("copilot-mic");
  // The thread list loads in after the mic appears (beside it, or on its own tab on a phone): let it settle first.
  await expect(page.getByText("Nothing open. Plan a trade to start a ticker.")).toBeAttached();
  await page.waitForLoadState("networkidle"); // the Briefing's lines read in above the box and move the mic down
  await mic.hover();
  const box = (await mic.boundingBox())!;
  await page.mouse.down();
  await expect(page.getByTestId("copilot-voice-status")).toContainText("release to transcribe");
  await page.waitForTimeout(ms);
  return { box, release: () => page.mouse.up() };
}

const autoSend = (page: Page) => page.getByLabel("Auto-send what I say");

test("hold, release: the words go straight out with auto-send on (the default)", async ({ page }) => {
  const seen = await lab(page);
  await page.goto("/copilot-lab");
  await page.getByLabel("Message").click(); // the idle box opens when used
  await expect(autoSend(page)).toBeChecked();
  const { release } = await hold(page);
  await expect(page.getByTestId("copilot-voice-status")).toContainText(/0:0\d/);
  await release();
  await expect(page.getByText("NBIS is above its 15-minute high.")).toBeVisible();
  expect(seen.transcribes).toEqual(["audio"]);
  expect(seen.chats.at(-1)!.messages.at(-1)!.content).toBe(SPOKEN);
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("");
});

test("with auto-send off the words wait in the box for review, and the setting is remembered", async ({ page }) => {
  const seen = await lab(page);
  await page.goto("/copilot-lab");
  await page.getByLabel("Message").click(); // the idle box opens when used
  await autoSend(page).uncheck();
  await page.reload();
  await page.getByLabel("Message").click();
  await expect(autoSend(page)).not.toBeChecked();
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Quick one:");
  const { release } = await hold(page);
  await release();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(`Quick one: ${SPOKEN}`);
  await expect(page.getByText("Heard you. Review the message, then Send.")).toBeVisible();
  expect(seen.chats).toHaveLength(0);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("NBIS is above its 15-minute high.")).toBeVisible();
  expect(seen.chats[0].messages.at(-1)!.content).toBe(`Quick one: ${SPOKEN}`);
  await expect(page.getByText("Heard you. Review the message, then Send.")).toHaveCount(0);
});

test("a short tap starts tap mode; the next tap stops; Cancel and sliding away send nothing", async ({ page }) => {
  const seen = await lab(page);
  await page.goto("/copilot-lab");
  const mic = page.getByTestId("copilot-mic");
  await mic.click();
  await expect(page.getByTestId("copilot-voice-status")).toContainText("tap the mic to stop");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("copilot-voice-status")).toHaveCount(0);

  const { box } = await hold(page);
  await page.mouse.move(box.x - 200, box.y - 150, { steps: 4 });
  await expect(page.getByTestId("copilot-voice-status")).toContainText("Let go to cancel");
  await page.mouse.up();
  await expect(page.getByTestId("copilot-voice-status")).toHaveCount(0);
  expect(seen.transcribes).toEqual([]);

  await mic.click();
  await expect(page.getByTestId("copilot-voice-status")).toContainText("tap the mic to stop");
  await page.waitForTimeout(500);
  await mic.click();
  await expect(page.getByText("NBIS is above its 15-minute high.")).toBeVisible();
  expect(seen.transcribes).toEqual(["audio"]);
});

test("a refused microphone says how to allow it", async ({ page }) => {
  const seen = await lab(page, { denied: true });
  await page.goto("/copilot-lab");
  await page.getByTestId("copilot-mic").click();
  await expect(page.getByTestId("copilot-voice-status")).toContainText("Microphone access is blocked");
  expect(seen.transcribes).toEqual([]);
});

test("without a server transcriber the browser listens, and only its tickers are cleaned up", async ({ page }) => {
  const seen = await lab(page, { configured: false, recognition: true });
  await page.goto("/copilot-lab");
  await page.getByLabel("Message").click(); // the idle box opens when used
  await autoSend(page).uncheck();
  const { release } = await hold(page);
  await release();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("NBIS over the high");
  expect(seen.transcribes).toEqual(["text"]);
});

test("with neither a transcriber nor browser recognition there is no mic", async ({ page }) => {
  await lab(page, { configured: false });
  await page.goto("/copilot-lab");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeVisible();
  await expect(page.getByTestId("copilot-mic")).toHaveCount(0);
  await expect(autoSend(page)).toHaveCount(0);
});

test("at 375 px the mic is a 44 px thumb target beside Send, and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page);
  await page.goto("/copilot-lab");
  await expect(page.getByText("Nothing open. Plan a trade to start a ticker.")).toBeVisible();
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click(); // a phone shows the conversation on its own tab
  await page.getByLabel("Message").click(); // the idle box opens when used
  const mic = (await page.getByTestId("copilot-mic").boundingBox())!;
  const send = (await page.getByRole("button", { name: "Send", exact: true }).boundingBox())!;
  expect(mic.width).toBeGreaterThanOrEqual(44);
  expect(mic.height).toBeGreaterThanOrEqual(44);
  expect(mic.x + mic.width).toBeLessThanOrEqual(375);
  expect(Math.abs(mic.y + mic.height / 2 - (send.y + send.height / 2))).toBeLessThan(8);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  const { release } = await hold(page);
  await expect(page.getByRole("button", { name: "Cancel" })).toBeInViewport();
  if (process.env.VOICE_SHOT) await page.screenshot({ path: process.env.VOICE_SHOT });
  await release();
});
