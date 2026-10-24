"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { chartLink, fetchOptionMark, MARK_STALE_SECONDS, type OptionMark } from "@/lib/chartJournal";

// Older API responses still render their history, but cannot identify a linked event.
type Sent = { id?: string; contract?: string; quoted_at?: number | null;
  kind: "giveback" | "expiry_first" | "expiry_final" | "hold_hour"; detected_at: number; contracts: number; mark: number | null; bid?: number | null;
  gain: number | null; gain_pct: number | null; peak_gain: number | null; peak_gain_pct: number | null;
  delivery: "pending" | "sending" | "sent" | "expired" | "unknown"; error: string | null; delivered_at: number | null };
type Watch = { peak_gain: number | null; peak_gain_pct: number | null; armed: boolean; fired: boolean; peak_at: number | null };
// The optional field keeps older API responses on the original +$50 rule.
type Body = { enabled: boolean; giveback_dollar_floor_applies?: boolean; alerts: Sent[]; watch: Watch | null };

const KIND: Record<Sent["kind"], string> = { giveback: "Give-back triggered", expiry_first: "Expires today", expiry_final: "30 minutes to the close",
  hold_hour: "Open an hour: re-decide" };
const DELIVERY: Record<Sent["delivery"], string> = { pending: "not sent yet", sending: "sending", sent: "accepted by ntfy; phone display unconfirmed",
  expired: "not sent: too late to be useful", unknown: "may have reached your phone, so it was not resent" };

const money = (v: number | null) => v == null ? "?" : `${v >= 0 ? "+" : "-"}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null) => v == null ? "?" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`;
const time = (s: number) => `${new Date(s * 1000).toLocaleString("en-US", { timeZone: "America/New_York", year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET`;

// The open position as it is now, next to the alert's saved snapshot: one quote through the dashboard's 60-second cache.
function PositionNow({ tradeId }: { tradeId: string }) {
  const [read, setRead] = useState<{ loading: boolean; data?: OptionMark; stale?: boolean; error?: string }>({ loading: true });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    fetchOptionMark(tradeId).then(data => { if (active) setRead({ loading: false, data,
      stale: data.quoted_at != null && Date.now() / 1000 - data.quoted_at > MARK_STALE_SECONDS }); },
      err => { if (active) setRead({ loading: false, error: err instanceof Error ? err.message : "The current price could not be read." }); });
    return () => { active = false; };
  }, [tradeId, attempt]);

  const { data, stale } = read;
  const pnlTone = data?.open_pnl == null ? "" : data.open_pnl >= 0 ? "text-emerald-400" : "text-red-400";
  return <div data-testid="position-now" aria-live="polite" className="space-y-1 rounded-md border p-3">
    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Now</h4>
    {read.loading && <p role="status" className="text-muted-foreground">Reading the current price…</p>}
    {!read.loading && read.error && <p role="alert" className="text-amber-300">Current price unavailable. {read.error}</p>}
    {!read.loading && data && (data.mark == null ? <p className="text-muted-foreground">No current quote came back for this contract.</p> : <>
      <p className={`text-base font-semibold tabular-nums ${pnlTone}`}>Open P&L now {money(data.open_pnl)}</p>
      <p>
        {data.open != null && <>{data.open} contract{data.open === 1 ? "" : "s"} open. </>}
        {data.basis === "last" ? "Last trade" : "Option midpoint"} ${data.mark.toFixed(2)} per share.
        {data.bid != null && <> Bid ${data.bid.toFixed(2)} per share.</>}
      </p>
      {data.quoted_at != null && <p className={`text-xs ${stale ? "text-amber-300" : "text-muted-foreground"}`}>{stale ? "Stale: quoted" : "Quoted"} {time(data.quoted_at)}.</p>}
    </>)}
    {!read.loading && <button type="button" onClick={() => { setRead({ loading: true }); setAttempt(n => n + 1); }}
      className="inline-flex min-h-11 items-center rounded-md border px-3 font-medium hover:bg-muted">{read.error ? "Try again" : "Refresh"}</button>}
  </div>;
}

export default function TradePhoneAlerts({ tradeId, alertId, symbol, status }: { tradeId: string; alertId?: string; symbol: string; status: string }) {
  const [body, setBody] = useState<Body | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(apiUrl(`/trades/${tradeId}/phone-alerts`), { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("Alert read failed"); return r.json(); })
      .then(b => { if (active) setBody(b); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [tradeId]);

  if (!alertId && (!body || (!body.alerts.length && !(body.enabled && body.watch)))) return null;
  const selected = alertId ? body?.alerts.find(a => a.id === alertId) : undefined;
  const history = body?.alerts.filter(a => a !== selected) ?? [];
  const rows = <ul className="mt-1 divide-y">{history.map(a => <li key={a.id ?? `${a.kind}-${a.detected_at}`} className="py-2">
    <span className="font-medium">{KIND[a.kind]}</span>
    <span className="text-muted-foreground"> · {time(a.detected_at)} · {DELIVERY[a.delivery]}</span>
    <div className="text-muted-foreground">
      {a.kind === "giveback" && <>Was up {money(a.peak_gain)} ({pct(a.peak_gain_pct)}), </>}
      {a.mark != null ? <>at {money(a.gain)} ({pct(a.gain_pct)}) with {a.contracts} open</> : <>no live quote, {a.contracts} open</>}
    </div>
  </li>)}</ul>;
  return <section aria-label="Phone alerts" data-testid="trade-phone-alerts" className={`rounded-lg border bg-card p-5 text-sm ${alertId ? "border-primary/60" : ""}`}>
    <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{alertId ? "Position alert" : "Phone alerts"}</h2>
    {alertId && !body && <p role="status">{failed ? "This alert could not be loaded. Reload the page to try again." : "Loading the selected alert…"}</p>}
    {alertId && body && !selected && <p role="status">This alert is unavailable for this position. It may have been removed or the link may be incorrect.</p>}
    {selected && <div data-testid="selected-position-alert" className="space-y-3">
      <div>
        <h3 className="text-base font-semibold">{KIND[selected.kind]}</h3>
        {selected.contract && <p>{selected.contract}</p>}
        <p className="text-muted-foreground">Triggered {time(selected.detected_at)}</p>
      </div>
      <p>
        {selected.kind === "giveback" && <>Peak {money(selected.peak_gain)} ({pct(selected.peak_gain_pct)}) → </>}
        {selected.mark != null ? <>at trigger {money(selected.gain)} ({pct(selected.gain_pct)}).</> : <>No reliable quote at trigger.</>}
        {selected.kind === "giveback" && <> Gain reached +3% or below after arming.</>}
      </p>
      <p className="text-muted-foreground">
        Saved snapshot, not a current quote. {selected.contracts} contract{selected.contracts === 1 ? "" : "s"} open at trigger.
        {selected.mark != null && <> Option midpoint ${(selected.mark / 100).toFixed(2)} per share.</>}
        {selected.bid != null && <> Bid ${(selected.bid / 100).toFixed(2)} per share.</>}
        {selected.quoted_at != null && <> Quoted {time(selected.quoted_at)}.</>}
        {status !== "open" && <> This position is now {status}.</>}
      </p>
      {status === "open" && <PositionNow tradeId={tradeId} />}
      <Link href={chartLink({ symbol, from: selected.detected_at, trade: tradeId })}
        className="inline-flex min-h-11 items-center rounded-md border px-3 font-medium hover:bg-muted">View underlying chart at alert</Link>
      <p className="text-xs text-muted-foreground">Delivery: {DELIVERY[selected.delivery]}.</p>
    </div>}
    {body?.enabled && body.watch && !alertId && <p className="text-muted-foreground">
      {body.watch.fired
        ? <>A give-back alert fired for this position (its delivery is listed below). It arms again only if the cost changes, for example when you buy more.</>
        : body.watch.armed
        ? <>Watching for a give-back: best so far {money(body.watch.peak_gain)} ({pct(body.watch.peak_gain_pct)}). An alert goes out if the gain falls to +3%.</>
        : <>Not armed yet: arms once it is up 10%{body.giveback_dollar_floor_applies !== false && " and $50"}{body.watch.peak_gain != null && <> (best so far {money(body.watch.peak_gain)}, {pct(body.watch.peak_gain_pct)})</>}.</>}
    </p>}
    {history.length > 0 && (alertId ? <details className="mt-3"><summary className="min-h-11 cursor-pointer py-3 text-muted-foreground">Other alerts ({history.length})</summary>{rows}</details> : rows)}
  </section>;
}
