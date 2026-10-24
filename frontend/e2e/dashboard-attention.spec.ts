import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { DecisionRecord, GmailHealth, PositionQuote, SyncJob, Trade, TradePhoneAlert } from "../lib/api";
import type { LevelAlert } from "../lib/alerts";
import type { OpenPositionMeta, OpenPositionRow } from "../lib/dashboard";
import type { Earnings } from "../lib/symbolInfo";
import { buildAttention, type AttentionInputs } from "../lib/dashboardAttention";

const backend = path.resolve(__dirname, "../../backend");
const venvPython = path.join(backend, ".venv/bin/python");
const python = existsSync(venvPython) ? venvPython : "python3";
const seedEnv = { ...process.env, DATABASE_URL: `sqlite:///${backend}/data/e2e_seed.db` };

const TODAY = "2026-10-12"; // a Monday
const NOW = Date.parse("2026-10-12T15:00:00Z");
const meta = (over: Partial<OpenPositionMeta> = {}): OpenPositionMeta => ({ openedQty: 2, exitedQty: 0, qtyLeft: 2, capitalLeft: 300,
  avgCostLeft: 150, realizedSoFar: null, lastActivityAt: "2026-10-01T10:00:00", direction: "long", ...over });
const option = (id: string, ticker: string, expiration: string | null, over: Partial<OpenPositionMeta> = {}): OpenPositionRow => ({
  trade: { id, ticker, instrument_type: "option", expiration, strike: 100, option_type: "call", status: "open" } as Trade, meta: meta(over) });
const stock = (id: string, ticker: string, over: Partial<OpenPositionMeta> = {}): OpenPositionRow => ({
  trade: { id, ticker, instrument_type: "stock", expiration: null, strike: null, option_type: null, status: "open" } as Trade, meta: meta(over) });
const mark = (mid: number | null, underlying: number | null = null): PositionQuote => ({ ticker: "", underlying_price: underlying,
  option_last_price: null, option_bid: null, option_ask: null, option_mid: mid, option_iv: null });
const earnings = (date: string | null, state: Earnings["state"] = "ready"): Earnings => ({ state, source: "Tradier corporate calendar",
  fetched_at: 1, message: null, reports: [], next: date ? { date, status: "estimated", label: "Q3" } : null });
const wait = (id: string, expiry: string, over: Partial<DecisionRecord> = {}): DecisionRecord => ({ id, opportunity_id: `opp-${id}`, received_at: "2026-10-12T13:00:00Z", decision: "wait", actor: "human",
  symbol: "MU", wait_condition: "Reclaims VWAP on volume", wait_expiry: expiry, evidence: { packet: { sample_data: false } }, ...over } as DecisionRecord);
const job = (job_type: string, status: SyncJob["status"], over: Partial<SyncJob> = {}): SyncJob => ({ job_type, label: job_type, status,
  error_summary: null, message: null, finished_at: "2026-10-12T13:00:00Z", updated_at: null, last_run_at: null, ...over } as SyncJob);
const fired = (id: string, minutesAgo: number, over: Partial<LevelAlert> = {}): LevelAlert => ({ id, symbol: "SPY", price: 700,
  condition: "crosses", direction: "up", label: "", state: "fired", event: { level: 700, price: 700.12, source: "stream",
    event_at: (NOW - minutesAgo * 60000) / 1000, detected_at: 0, delivery: "sent", attempts: 1, delivered_at: null, error: null }, ...over } as LevelAlert);
const health = (status: GmailHealth["status"]): GmailHealth => ({ status, message: `Gmail ${status}`, action: null, listener_enabled: true,
  last_notification_at: null, last_import_at: null, watch_expires_at: null, data_version: "x" });
const base = (over: Partial<AttentionInputs> = {}): AttentionInputs => ({ rows: [], quotes: {}, quoteError: false, today: TODAY, now: NOW,
  decisions: [], alerts: [], jobs: [], gmail: health("live"), earnings: {}, ...over });

test("attention rules: each trigger, its non-trigger twin, priority order and stable ties", () => {
  const rows = [
    option("expired", "NBIS", "2026-10-09"), option("today", "QQQ", "2026-10-12"), option("thu", "NVDA", "2026-10-15"),
    option("later", "AMD", "2026-10-16"), option("far", "MU", "2026-11-20"), stock("basis", "RNXT", { avgCostLeft: null }),
    stock("priced", "AAPL"),
  ];
  const quotes = { expired: mark(null), today: mark(1), thu: mark(2), later: mark(3), far: mark(null), basis: mark(null, 1), priced: mark(null, 240) };
  const { items, unavailable } = buildAttention(base({
    rows, quotes,
    earnings: { QQQ: earnings(null, "none"), NVDA: earnings("2026-10-15"), AMD: earnings("2026-10-20"), MU: earnings("2026-10-14") },
    gmail: health("down"),
    jobs: [job("trade_rebuild", "failed", { label: "Rebuild trades", error_summary: "boom" }), job("gmail_sync", "succeeded")],
    alerts: [fired("recent", 30), fired("old", 25 * 60), fired("active", 5, { state: "active" })],
    decisions: [wait("open", "2026-10-12T19:00:00Z"), wait("ended", "2026-10-12T14:00:00Z"),
      wait("sample", "2026-10-13T19:00:00Z", { evidence: { packet: { sample_data: true } } }),
      wait("agent", "2026-10-13T19:00:00Z", { actor: "agent:dot" }), wait("skip", "2026-10-13T19:00:00Z", { decision: "skip" }),
      wait("superseded", "2026-10-13T19:00:00Z", { opportunity_id: "opp-x" }),
      wait("later-take", "2026-10-13T19:00:00Z", { opportunity_id: "opp-x", decision: "take", received_at: "2026-10-12T14:00:00Z" }),
      wait("agent-later", "2026-10-13T19:00:00Z", { opportunity_id: "opp-open", actor: "agent:dot", received_at: "2026-10-12T14:30:00Z" })],
  }));
  expect(items.map((item) => item.id)).toEqual([
    "expired-open:expired", // integrity: expired records sort by expiry date, before ticker-keyed gaps
    "no-price:far", "no-basis:basis",
    "gmail", "job:trade_rebuild",
    "expiring:today", "earnings:far", "earnings:thu", "expiring:thu",
    "alert:recent",
    "wait:open",
  ]);
  expect(unavailable).toEqual([]); // "none" (an ETF without earnings) is an answer, not a gap
  const byId = Object.fromEntries(items.map((item) => [item.id, item]));
  expect(byId["expired-open:expired"].title).toBe("NBIS 100C 10/9 still open after expiry");
  expect(byId["expiring:today"].when).toBe("Today");
  expect(byId["earnings:thu"].title).toBe("NVDA earnings 10/15, on expiry");
  expect(byId["earnings:thu"].detail).toContain("time of day is not published");
  expect(byId["earnings:far"].title).toBe("MU earnings 10/14, before expiry");
  expect(byId["earnings:far"].href).toBe("/charts?symbol=MU");
  expect(byId["job:trade_rebuild"].detail).toBe("boom");
  expect(byId["job:trade_rebuild"].href).toBe("/?sync=open");
  expect(byId["alert:recent"].title).toBe("SPY crossed 700.00");
  expect(byId["alert:recent"].when).toBe("30m ago");
  expect(byId["wait:open"].href).toBe("/practice?decision=open#saved-decisions");
  expect(byId["wait:open"].detail).toContain("Reclaims VWAP on volume");
  // Expired options get no "no price" noise; AMD 10/16 is outside the 3-day window and its earnings fall after expiry.
  expect(items.some((item) => item.id === "no-price:expired" || item.id === "expiring:later" || item.id === "earnings:later")).toBe(false);
  // Same inputs, same order.
  expect(buildAttention(base({ rows: [...rows].reverse(), quotes, gmail: health("down") })).items.map((i) => i.id))
    .toEqual(buildAttention(base({ rows, quotes, gmail: health("down") })).items.map((i) => i.id));
});

const phoneAlert = (id: string, minutesAgo: number, over: Partial<TradePhoneAlert> = {}): TradePhoneAlert => ({ id, kind: "giveback",
  detected_at: (NOW - minutesAgo * 60000) / 1000, contracts: 2, gain: 24, gain_pct: 0.03, peak_gain: 204, peak_gain_pct: 0.255, ...over });

test("a give-back alert stays listed for the rest of its day while the position is open", () => {
  const rows = [option("nvda", "NVDA", "2026-10-30"), option("amd", "AMD", "2026-10-30"), option("mu", "MU", "2026-10-30"), option("x", "X", "2026-10-30")];
  const quotes = { nvda: mark(1), amd: mark(1), mu: mark(1), x: mark(1) };
  const { items, unavailable } = buildAttention(base({ rows, quotes, phoneAlerts: {
    // The later of two give-backs today is the one listed; an expiry alert is not a give-back.
    nvda: [phoneAlert("first", 90, { gain: 10 }), phoneAlert("second", 20), phoneAlert("expiry", 5, { kind: "expiry_first" })],
    amd: [phoneAlert("yesterday", 16 * 60)], // 23:00 ET the day before
    mu: null,
  } }));
  expect(items.map((item) => item.id)).toEqual(["giveback:second"]);
  expect(items[0]).toMatchObject({ priority: "alert", title: "NVDA 100C 10/30 gave back its gain", when: "20m ago", href: "/trades/nvda?alert=second",
    detail: "Peak +$204 (+26%), +$24 (+3%) at the alert. 2 open now." });
  expect(unavailable).toEqual(["Phone alerts for MU 100C 10/30"]);
  // Newer give-backs sort ahead of older price alerts, like the price alerts among themselves.
  expect(buildAttention(base({ rows, quotes, alerts: [fired("price", 30)], phoneAlerts: { nvda: [phoneAlert("g", 10)] } })).items.map((i) => i.id))
    .toEqual(["giveback:g", "alert:price"]);
});

test("attention discloses failed sources instead of reading them as quiet", () => {
  const rows = [option("a", "NVDA", "2026-10-30"), option("b", "AMD", "2026-10-30")];
  const failed = buildAttention(base({ rows, quotes: {}, quoteError: true, gmail: null, jobs: null, alerts: null,
    earnings: { NVDA: null, AMD: earnings(null, "unavailable") } }));
  expect(failed.items).toEqual([]); // a failed quote request is already disclosed above the panel
  expect(failed.unavailable).toEqual(["Earnings dates for AMD, NVDA", "Gmail import status", "Sync job status", "Price alerts"]);
  const quiet = buildAttention(base({ gmail: health("off") }));
  expect(quiet).toEqual({ items: [], unavailable: [] });
  expect(buildAttention(base({ gmail: health("degraded") })).items[0].title).toBe("Fill import is degraded");
  expect(buildAttention(base({ rows: [option("n", "X", null)], quotes: { n: mark(1) } })).items.map((i) => i.id)).toEqual(["no-expiry:n"]);
  expect(buildAttention(base({ rows: [stock("u", "X", { direction: "unknown" })], quotes: { u: mark(null, 1) } })).items.map((i) => i.id)).toEqual(["no-basis:u"]);
});

test("a give-back alert from today opens its exact alert from Attention at phone width", async ({ page }) => {
  const seeded = JSON.parse(execFileSync(python, ["-c", `
import json
from datetime import datetime,timedelta
from sqlmodel import Session,select
from app.database import engine
from app.engine.position_alerts import anchor
from app.models import Account,Fill,PositionAlert,Trade,TradeFill
assert engine.url.database.endswith('/data/e2e_seed.db')
with Session(engine) as db:
    roth=db.exec(select(Account.id).where(Account.type=='roth_ira')).one()
    trade=db.exec(select(Trade).where(Trade.ticker=='AAPL',Trade.account_id==roth,Trade.status=='open',Trade.instrument_type=='option')).one()
    entries=db.exec(select(Fill).join(TradeFill,TradeFill.fill_id==Fill.id).where(TradeFill.trade_id==trade.id,TradeFill.role=='entry')).all()
    alert=PositionAlert(account_id=roth,source_key=anchor(entries),kind='giveback',generation=99,trade_id=trade.id,contract='AAPL 230C',
        contracts=6,avg_cost=200,mark=206,bid=205,gain=36,gain_pct=0.03,peak_gain=660,peak_gain_pct=0.55,
        detected_at=datetime.utcnow()-timedelta(minutes=1),delivery='sent')
    db.add(alert);db.commit()
    print(json.dumps({"alert":str(alert.id),"trade":str(trade.id)}))
`], { cwd: backend, env: seedEnv, encoding: "utf8" }).trim()) as { alert: string; trade: string };
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const panel = page.getByRole("region", { name: "Attention" });
    const item = panel.locator(`[data-attention-id="giveback:${seeded.alert}"]`);
    await expect(item).toContainText("gave back its gain");
    await expect(item).toContainText("Peak +$660 (+55%), +$36 (+3%) at the alert.");
    await expect(item).toHaveAttribute("href", `/trades/${seeded.trade}?alert=${seeded.alert}`);
    await panel.screenshot({ path: test.info().outputPath("dashboard-attention-giveback-phone.png"), animations: "disabled" });
    // The Exit Habits card opens the same alert, not just its trade.
    const habits = page.getByTestId("exit-habits").getByTestId("exit-habits-alert").filter({ hasText: "AAPL 230C" });
    await expect(habits.getByRole("link")).toHaveAttribute("href", `/trades/${seeded.trade}?alert=${seeded.alert}`);
    await item.click();
    await expect(page.getByTestId("selected-position-alert")).toContainText("Give-back triggered");
  } finally {
    // Leave no alert behind: the Exit Habits seed only runs on a database without one.
    execFileSync(python, ["-c", `
import sys,uuid
from sqlmodel import Session,delete
from app.database import engine
from app.models import PositionAlert
with Session(engine) as db:
    db.exec(delete(PositionAlert).where(PositionAlert.id==uuid.UUID(sys.argv[1])));db.commit()
`, seeded.alert], { cwd: backend, env: seedEnv });
  }
});

test("attention panel streams in, links to its records and opens Sync from a job item", async ({ page }) => {
  const alertId = execFileSync(python, ["-c", `
import time,uuid
from datetime import datetime,timedelta,date
from sqlmodel import Session
from app.database import engine
from app.models import LevelAlert,LevelAlertEvent
assert engine.url.database.endswith('/data/e2e_seed.db')
now=datetime.utcnow()
with Session(engine) as db:
    alert=LevelAlert(symbol='SPY',price=701.5,created_on=date.today(),condition='touches',session='regular',direction='up',
        source_kind='level',label='Prior high',state='fired',fired_at=now-timedelta(minutes=20))
    db.add(alert);db.flush()
    db.add(LevelAlertEvent(alert_id=alert.id,generation=1,level=701.5,price=701.55,source='stream',event_at=now-timedelta(minutes=20),delivery='sent'))
    db.commit();print(alert.id)
`], { cwd: backend, env: seedEnv, encoding: "utf8" }).trim();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto("/");
    const panel = page.getByRole("region", { name: "Attention" });
    const alert = panel.locator(`[data-attention-id="alert:${alertId}"]`);
    await expect(alert).toContainText("SPY touched 701.50");
    await expect(alert).toContainText("Prior high · Fired at 701.55.");
    await expect(alert).toHaveAttribute("href", "/charts?symbol=SPY");
    // Seeded positions have no dated earnings source offline; the panel says so rather than staying silent.
    await expect(panel).toContainText("Could not check: Earnings dates for AAPL");
    const bounds = await Promise.all([page.getByLabel("Market and discovery", { exact: true }).boundingBox(), panel.boundingBox(),
      page.getByRole("region", { name: "Active Options" }).boundingBox()]);
    expect(Math.abs(bounds[0]!.y - bounds[1]!.y)).toBeLessThan(2); // Attention beside market context on wide screens.
    expect(bounds[1]!.y + bounds[1]!.height).toBeLessThan(bounds[2]!.y); // Warnings before positions and stats.
    await panel.screenshot({ path: test.info().outputPath("dashboard-attention-desktop.png"), animations: "disabled" });
    await page.screenshot({ path: test.info().outputPath("dashboard-attention-page-desktop.png"), animations: "disabled" });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await panel.screenshot({ path: test.info().outputPath("dashboard-attention-phone.png"), animations: "disabled" });
    await expect(panel).not.toContainText("Position checks cover");
    await page.goto("/?account=roth_ira&type=option");
    await expect(panel).toContainText("Position checks cover Roth IRA · options only");
    await page.goto("/?type=option&sync=open");
    await expect(page.getByRole("heading", { name: "Data Sync Center" })).toBeVisible();
    await expect.poll(() => new URL(page.url()).search).toBe("?type=option"); // the sync flag is cleared just after the dialog opens
    expect(errors).toEqual([]);
  } finally {
    execFileSync(python, ["-c", `
import sys,uuid
from sqlmodel import Session,delete
from app.database import engine
from app.models import LevelAlert,LevelAlertEvent
with Session(engine) as db:
    db.exec(delete(LevelAlertEvent).where(LevelAlertEvent.alert_id==uuid.UUID(sys.argv[1])))
    db.exec(delete(LevelAlert).where(LevelAlert.id==uuid.UUID(sys.argv[1])))
    db.commit()
`, alertId], { cwd: backend, env: seedEnv });
  }
});
