import { expect, test, type Page } from "@playwright/test";
import type { PlanState, PlansView, PlanView } from "../lib/conditionalPlans";

const now = "2026-10-20T15:00:30.000000Z";
const t = (minutes: number) => new Date(Date.parse(now) + minutes * 60_000).toISOString().replace(".000Z", ".000000Z");
const bar = (start: number, close: number) => ({ time: Date.parse(t(start)) / 1000, end_time: Date.parse(t(start + 1)) / 1000, open: close, high: close + 1, low: close - 1, close });

function plan(state: PlanState, extra: Partial<PlanView> = {}): PlanView {
  const watched = state !== "pending_activation";
  return { plan_id: `cpl_${state}`, actor: "jo", session_date: "2026-10-20", symbol: "NBIS", direction: "long",
    trigger_price: 105, invalidation_price: 100, confirm_bars: 2, rationale: "Two closes above 105 confirm the breakout; a close below 100 ends it.",
    source: { kind: "stock_alert", id: "sta_fixture", sha256: "a".repeat(64), observed_at: t(-10), price: 103.4 },
    expires_at: t(120), created_at: t(-9), accepted_by_monitor: watched, cancel_requested: false, state,
    reason: watched ? { watching: "monitor_accepted", triggered: "confirmed_closes", invalidated: "invalidation_close", expired: "monitoring_window_ended",
      cancelled: "owner_cancelled", unavailable: "stale_source", pending_activation: "" }[state] : null,
    state_at: watched ? t(-1) : null, monitoring: state === "watching" || state === "triggered", heartbeat_at: watched ? t(0) : null,
    last_bar: watched ? { ...bar(-2, 106), consecutive: state === "triggered" ? 2 : 1 } : null, last_evaluated_at: watched ? t(-0.5) : null,
    events: watched ? [{ state, reason: "monitor_accepted", occurred_at: t(-1), bar: null }] : [], deliveries: [], ...extra };
}

function view(plans: PlanView[], extra: Partial<PlansView> = {}): PlansView {
  return { checked_at: now, enabled: true, app_flag: true, stock_watch: true, configured: true,
    readiness: { heartbeat: "fresh", heartbeat_at: t(0), monitor_enabled: true, session_date: "2026-10-20", session_open_at: t(-90),
      session_close_at: t(300), session_open_now: true, symbols: ["NBIS", "SPY"], selection_revision: 3 },
    max_daily_plans: 24, plans_today: plans.length, limit: 50, delivery: { channel: "ntfy phone push", configured: true }, plans, ...extra };
}

async function open(page: Page, body: PlansView) {
  await page.route("**/conditional-plans", (route) => route.fulfill({ json: body }));
  await page.goto("/morning/watches");
  await expect(page.getByTestId("plan-monitor")).toBeVisible();
}

async function fitsPhone(page: Page, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath(`price-watches-${name}-phone.png`), fullPage: true });
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

test("off feature says so plainly from the real backend, linked from Morning", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/morning");
  await page.getByRole("link", { name: "Jo’s price watches →" }).click();
  await expect(page).toHaveURL(/\/morning\/watches$/);
  await expect(page.getByTestId("plan-monitor")).toContainText("Price watches are off");
  await expect(page.getByTestId("plan-monitor")).toContainText("nothing below is being monitored");
  await expect(page.getByText("No current watches. Nothing is being monitored for you.")).toBeVisible();
  await fitsPhone(page, "off");
  expect(errors).toEqual([]);
});

test("watching, pending and triggered show monitoring truth and that triggered is not entered", async ({ page }) => {
  await open(page, view([plan("watching"), plan("pending_activation", { plan_id: "cpl_pending" }),
    plan("triggered", { deliveries: [{ event_state: "triggered", attempt: 1, result: "accepted", outcome: "sent", error_code: null, transport_receipt_id: "ntfy-1", occurred_at: t(-0.9) }] })]));
  await expect(page.getByTestId("plan-monitor")).toContainText("Monitor running");
  await expect(page.getByTestId("plan-monitor")).toContainText("Eligible tickers: NBIS, SPY · 3 of 24");
  const card = (state: string) => page.locator(`[data-testid=plan-card][data-state=${state}]`);
  await expect(card("watching").getByTestId("plan-badge")).toHaveText("Watching");
  await expect(card("watching").getByTestId("plan-monitoring")).toContainText("Active · heartbeat");
  await expect(card("watching")).toContainText("Alert after 2 consecutive completed 1-minute closes above 105. Ends on one close below 100.");
  await expect(card("watching")).toContainText("close 106 · 1 of 2 confirming");
  await expect(card("pending_activation").getByTestId("plan-badge")).toHaveText("Saved · not monitored yet");
  await expect(card("pending_activation")).toContainText("the app monitor has not picked it up");
  await expect(card("pending_activation").getByTestId("plan-monitoring")).toHaveText("Not active");
  await expect(card("triggered").getByTestId("plan-badge")).toHaveText("Triggered · not entered");
  await expect(card("triggered")).toContainText("It does not mean you entered, and no order was placed.");
  await expect(card("triggered")).toContainText("Sent to ntfy (your phone showing it is not confirmed)");
  await fitsPhone(page, "active");
});

test("stale heartbeat never reads as active monitoring", async ({ page }) => {
  const stale = view([plan("watching", { monitoring: false, heartbeat_at: t(-5) })]);
  stale.readiness = { ...stale.readiness, heartbeat: "stale", heartbeat_at: t(-5) };
  await open(page, stale);
  await expect(page.getByTestId("plan-monitor")).toContainText("Monitor not reporting");
  await expect(page.getByTestId("plan-monitor")).toContainText("Nothing is being watched right now");
  const card = page.getByTestId("plan-card");
  await expect(card.getByTestId("plan-badge")).toHaveText("Not monitored · monitor not reporting");
  await expect(card.getByTestId("plan-monitoring")).toContainText("Not active · last heartbeat");
  await expect(page.getByText("Watching", { exact: true })).toHaveCount(0);
  await fitsPhone(page, "stale");
});

test("ended states, unknown delivery and unavailable are explicit", async ({ page }) => {
  await open(page, view([
    plan("unavailable", { monitoring: false, deliveries: [{ event_state: "unavailable", attempt: 1, result: "unknown", outcome: "unknown", error_code: "result_not_recorded", transport_receipt_id: null, occurred_at: t(-0.5) }] }),
    plan("invalidated", { monitoring: false, deliveries: [{ event_state: "invalidated", attempt: 1, result: "failed", outcome: "failed", error_code: "ntfy_http", transport_receipt_id: null, occurred_at: t(-0.5) }] }),
    plan("expired", { monitoring: false }), plan("cancelled", { monitoring: false })]));
  const card = (state: string) => page.locator(`[data-testid=plan-card][data-state=${state}]`);
  await expect(page.getByText("No current watches. Nothing is being monitored for you.")).toBeVisible();
  await expect(card("unavailable").getByTestId("plan-badge")).toHaveText("Monitoring failed · not watched");
  await expect(card("unavailable")).toContainText("this is not a trade invalidation");
  await expect(card("unavailable")).toContainText("Unknown: it may have gone out; it will not be resent (result_not_recorded)");
  await expect(card("invalidated").getByTestId("plan-badge")).toHaveText("Invalidated");
  await expect(card("invalidated")).toContainText("Failed (ntfy_http)");
  await expect(card("expired").getByTestId("plan-badge")).toHaveText("Expired");
  await expect(card("cancelled").getByTestId("plan-badge")).toHaveText("Cancelled");
  for (const state of ["unavailable", "invalidated", "expired", "cancelled"]) await expect(card(state).getByTestId("plan-monitoring")).toHaveText("Stopped");
  await fitsPhone(page, "ended");
});
