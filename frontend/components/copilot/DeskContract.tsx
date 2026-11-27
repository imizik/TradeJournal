"use client";

import { useEffect, useState } from "react";
import { getDeskContract, type DeskContractData, type DeskContractFill, type DeskOrder, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

/*
 * A held option's own chart on the desk (docs/copilot-lab.md § The desk): with a held single-leg option selected, the
 * centre chart's header offers Stock / Contract, remembered per contract in this browser. Contract shows the option's
 * price for its latest session with trades (``GET /copilot/desk/contract``: Tradier's minute trades, as 2-minute candles
 * when they are dense, else a line through the prints), its mark (bid/ask midpoint) as a dotted line where the desk's
 * live prices saw it, his fills as lines at their premium (Robinhood's not-yet-emailed fills marked provisional), and at
 * the cursor: the price and which it is, his P&L in dollars for his size, and the stock's price at that moment.
 *
 * One read when the row is selected (so the toggle only shows when there is something to draw), then once a minute
 * while the Contract view is shown, visible and the market can move; the mark moves with the shared live prices in
 * between. No history: no toggle, never an invented line.
 */

const OCC = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/;
const VIEW_STORE = "desk.chart.contract.v1";
const REFRESH_MS = 60_000;
export const COLOR = { trade: "#e4e4e7", mark: "#7dd3fc", fill: "#e9a23b", provisional: "#e9a23b99" };
/** Two marks further apart than this are not joined: the desk was not open to see between them. */
export const MARK_GAP = 10 * 60;
/** A fill line further than this from the last price does not stretch the price scale. */
export const FILL_REACH = 0.6;
export const MAX_FILL_LINES = 6;
export const ET = "America/New_York";
const NO_ORDERS: DeskOrder[] = [];
export const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" });
export const nyDate = new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" });
export const premium = (value: number) => value.toFixed(2);
export const usd = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

export type HeldContract = {
  occ: string; symbol: string; label: string;
  /** The book's P&L terms (``book.tick``): cost a contract, contracts, side. */
  cost: number; quantity: number; sign: 1 | -1; scale: number;
  orders: DeskOrder[];
  /** His cut line, a share's premium (``book.cut_line`` / 100); null where the rule does not apply. */
  cut?: number | null;
};

/** The selected row as a held single-leg option the Contract view can draw, or null: a stock, a row without the book's
 * quote terms, a hidden ticker, or one leg of a structure (another option on the ticker held the other way). */
export function heldContract(row: DeskThread | null | undefined, rows: readonly DeskThread[] = []): HeldContract | null {
  const book = row?.book, tick = book?.tick, option = book?.option;
  if (!row || row.hidden || !row.symbol || !book || !tick || !option || tick.scale !== 100 || !OCC.test(tick.quote) || !(tick.cost > 0) || !(tick.quantity > 0)) return null;
  const legs = rows.filter(r => r !== row && r.key !== row.key && r.symbol === row.symbol && r.book?.option);
  if (legs.some(r => r.book?.option?.direction !== option.direction)) return null;
  const what = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
  return { occ: tick.quote, symbol: row.symbol, label: what.startsWith(`${row.symbol} `) ? what : `${row.symbol} ${what}`,
    cost: tick.cost, quantity: tick.quantity, sign: tick.sign, scale: tick.scale, orders: book.orders ?? NO_ORDERS,
    cut: book.cut_line != null && book.cut_line > 0 ? book.cut_line / 100 : null };
}

/** His P&L in dollars at a per-share premium, by the book's own formula (``tickedBook``). */
export const pnlAt = (held: Pick<HeldContract, "cost" | "quantity" | "sign" | "scale">, price: number) =>
  Math.round(held.sign * (price * held.scale - held.cost) * held.quantity * 100) / 100;

/** Robinhood's fills on this contract today that the journal does not have yet (#776's order lines), as fill lines. */
export function provisionalFills(orders: readonly DeskOrder[]): DeskContractFill[] {
  return orders.filter(o => o.instrument === "option" && o.filled > 0 && o.filled_at && o.avg && o.pairing === "provisional" && o.price_kind !== "net")
    .map(o => {
      const side = o.action.toLowerCase().startsWith("buy") ? "buy" as const : "sell" as const;
      return { at: o.filled_at!, side, opening: o.action.toLowerCase().endsWith("open"), contracts: o.filled, price: o.avg!, provisional: true,
        text: `${side === "buy" ? "Bought" : "Sold"} ${o.filled} at ${premium(o.avg!)} (Robinhood, provisional)` };
    });
}

const readViews = (): Record<string, "contract"> => {
  try { const saved = JSON.parse(window.localStorage.getItem(VIEW_STORE) ?? "{}"); return saved && typeof saved === "object" ? saved : {}; } catch { return {}; }
};

export type ContractView = { available: boolean; view: "stock" | "contract"; pick(view: "stock" | "contract"): void; data: DeskContractData | null };

/** The selected contract's read and the remembered Stock / Contract choice for it. */
export function useContractView(held: HeldContract | null): ContractView {
  const occ = held?.occ ?? null, symbol = held?.symbol ?? null;
  const [read, setRead] = useState<DeskContractData | null>(null);
  const [views, setViews] = useState<Record<string, "contract">>({});
  const [tick, setTick] = useState(0);
  useEffect(() => { setViews(readViews()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  useEffect(() => {
    if (!occ || !symbol) return;
    const controller = new AbortController();
    getDeskContract(symbol, occ, controller.signal)
      // A failed or empty refresh keeps the chart already shown for this contract.
      .then(data => { if (!controller.signal.aborted) setRead(prev => data.state !== "ok" && prev?.state === "ok" && prev.occ === occ && data.state === "unavailable" ? prev : { ...data, occ }); })
      .catch(() => { if (!controller.signal.aborted) setRead(prev => prev?.occ === occ ? prev : null); });
    return () => controller.abort();
  }, [occ, symbol, tick]);
  const data = read && occ && read.occ === occ ? read : null;
  const available = data?.state === "ok";
  const view = available && occ && views[occ] === "contract" ? "contract" : "stock";
  const live = !!data?.live;
  useEffect(() => {
    if (view !== "contract" || !live) return;
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [view, live, occ]);
  const pick = (next: "stock" | "contract") => {
    if (!occ) return;
    setViews(prev => {
      const out = { ...prev };
      if (next === "contract") out[occ] = "contract"; else delete out[occ];
      try { window.localStorage.setItem(VIEW_STORE, JSON.stringify(out)); } catch { /* this visit only */ }
      return out;
    });
  };
  return { available, view, pick, data: available ? data : null };
}

/** Stock / Contract, beside the timeframes in the chart header. */
export function ChartViewToggle({ view, onPick }: { view: "stock" | "contract"; onPick(view: "stock" | "contract"): void }) {
  return (
    <div role="group" aria-label="Chart of" data-testid="desk-chart-view" className="flex gap-1">
      {(["stock", "contract"] as const).map(item => (
        <button key={item} type="button" aria-pressed={view === item} onClick={() => onPick(item)}
          className={cn("min-h-11 rounded border px-2 text-xs sm:min-h-0 sm:py-0.5",
            view === item ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {item === "stock" ? "Stock" : "Contract"}
        </button>
      ))}
    </div>
  );
}

export type Point = { time: number; price: number };
export type Hover = { time: number; x: number; width: number };

/** The newest of ``points`` at or before ``at`` (sorted by time), or undefined. */
export function atOrBefore<T extends { time: number }>(points: readonly T[], at: number): T | undefined {
  let low = 0, high = points.length;
  while (low < high) { const mid = (low + high) >>> 1; if (points[mid].time <= at) low = mid + 1; else high = mid; }
  return points[low - 1];
}

/** Server marks plus the live one in its 2-minute slot (today only, never a stale one). */
export function mergedMarks(marks: readonly Point[], live: { last: number; at: number; stale: boolean } | null, day: string | null | undefined, step: number): Point[] {
  if (!live || live.stale || !day || nyDate.format(live.at * 1000) !== day) return [...marks];
  const slot = live.at - (live.at % step);
  return [...marks.filter(m => m.time < slot), { time: slot, price: live.last }];
}

/** What the cursor reads at ``at``: the trade or mark in its slot, else the newest one before it (with its time). */
export function priceAt(bars: readonly { time: number; close: number }[], marks: readonly Point[], at: number):
  { price: number; kind: "trade" | "mark"; time: number } | null {
  const trade = atOrBefore(bars, at), mark = atOrBefore(marks, at);
  if (!trade && !mark) return null;
  if (trade && (!mark || trade.time >= mark.time)) return { price: trade.close, kind: "trade", time: trade.time };
  return { price: mark!.price, kind: "mark", time: mark!.time };
}
