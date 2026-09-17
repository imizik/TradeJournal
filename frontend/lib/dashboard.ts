import type { Fill, PositionQuote, Trade } from "@/lib/api";

export type PositionDirection = "long" | "short" | "unknown";

export type OpenPositionMeta = {
  openedQty: number;
  exitedQty: number;
  qtyLeft: number;
  capitalLeft: number;
  realizedSoFar: number | null;
  lastActivityAt: string;
  direction: PositionDirection;
};

export type OpenPositionRow = {
  trade: Trade;
  meta: OpenPositionMeta;
};

export function isEntryFill(fill: Fill) {
  return fill.side === "buy_to_open" || fill.side === "sell_to_open" || fill.side === "buy";
}

export function buildOpenPositionMeta(trade: Trade, fills: Fill[]): OpenPositionMeta {
  const entryFills = fills.filter(isEntryFill);
  const entryQty = entryFills.reduce((sum, fill) => sum + fill.contracts, 0);
  const exitedQty = fills.filter((fill) => !isEntryFill(fill)).reduce((sum, fill) => sum + fill.contracts, 0);
  const openedQty = entryQty || trade.contracts;
  const qtyLeft = Math.max(openedQty - exitedQty, 0);
  const entrySide = entryFills[0]?.side;
  const direction: PositionDirection =
    entrySide === "sell_to_open" || entrySide === "sell"
      ? "short"
      : entrySide === "buy_to_open" || entrySide === "buy"
        ? "long"
        : "unknown";

  return {
    openedQty,
    exitedQty,
    qtyLeft,
    capitalLeft: qtyLeft * trade.avg_entry_premium,
    realizedSoFar: trade.realized_pnl,
    lastActivityAt: fills.at(-1)?.executed_at ?? trade.opened_at,
    direction,
  };
}

export function getCurrentMark(trade: Trade, quote: PositionQuote | undefined): number | null {
  if (!quote) return null;
  if (trade.instrument_type === "stock") return quote.underlying_price;
  return quote.option_mid ?? quote.option_last_price;
}

export function getPositionMarketValue(
  trade: Trade,
  meta: OpenPositionMeta,
  quote: PositionQuote | undefined,
): number | null {
  const mark = getCurrentMark(trade, quote);
  if (mark == null) return null;
  const markPerContract = trade.instrument_type === "option" ? mark * 100 : mark;
  return Math.abs(markPerContract * meta.qtyLeft);
}

export function computeUnrealizedPnl(
  trade: Trade,
  meta: OpenPositionMeta,
  quote: PositionQuote | undefined,
): number | null {
  const currentMark = getCurrentMark(trade, quote);
  if (currentMark == null || meta.direction === "unknown") return null;

  // avg_entry_premium is per contract; option marks from yfinance are per-share.
  const markPerContract = trade.instrument_type === "option" ? currentMark * 100 : currentMark;
  const perUnitPnl =
    meta.direction === "short"
      ? trade.avg_entry_premium - markPerContract
      : markPerContract - trade.avg_entry_premium;
  return perUnitPnl * meta.qtyLeft;
}

export function formatHoldDuration(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  if (value < 1) return "<1m";

  const minutes = Math.round(value);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const remainingMinutes = minutes % 60;

  if (days > 0) return `${days}d${hours > 0 ? ` ${hours}h` : ""}`;
  if (hours > 0) return `${hours}h${remainingMinutes > 0 ? ` ${remainingMinutes}m` : ""}`;
  return `${minutes}m`;
}
