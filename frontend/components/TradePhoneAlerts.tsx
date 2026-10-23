"use client";
import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

// Open-trade phone alerts for this position: give-back after a gain, and last-day expiry. Alerts only; nothing trades.
type Sent = { kind: "giveback" | "expiry_first" | "expiry_final"; detected_at: number; contracts: number; mark: number | null;
  gain: number | null; gain_pct: number | null; peak_gain: number | null; peak_gain_pct: number | null;
  delivery: "pending" | "sending" | "sent" | "expired" | "unknown"; error: string | null; delivered_at: number | null };
type Watch = { peak_gain: number | null; peak_gain_pct: number | null; armed: boolean; fired: boolean; peak_at: number | null };
// The optional field keeps older API responses on the original +$50 rule.
type Body = { enabled: boolean; giveback_dollar_floor_applies?: boolean; alerts: Sent[]; watch: Watch | null };

const KIND: Record<Sent["kind"], string> = { giveback: "Gave back its gain", expiry_first: "Expires today", expiry_final: "30 minutes to the close" };
const DELIVERY: Record<Sent["delivery"], string> = { pending: "not sent yet", sending: "sending", sent: "sent to your phone",
  expired: "not sent: too late to be useful", unknown: "may have reached your phone, so it was not resent" };

const money = (v: number | null) => v == null ? "?" : `${v >= 0 ? "+" : "-"}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null) => v == null ? "?" : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`;
const time = (s: number) => new Date(s * 1000).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default function TradePhoneAlerts({ tradeId }: { tradeId: string }) {
  const [body, setBody] = useState<Body | null>(null);

  useEffect(() => {
    let active = true;
    fetch(apiUrl(`/trades/${tradeId}/phone-alerts`), { cache: "no-store" })
      .then(r => r.ok ? r.json() : null).then(b => { if (active) setBody(b); }).catch(() => undefined);
    return () => { active = false; };
  }, [tradeId]);

  if (!body || (!body.alerts.length && !(body.enabled && body.watch))) return null;
  return <section aria-label="Phone alerts" data-testid="trade-phone-alerts" className="rounded-lg border bg-card p-5 text-sm">
    <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Phone alerts</h2>
    {body.enabled && body.watch && <p className="text-muted-foreground">
      {body.watch.fired
        ? <>A give-back alert fired for this position (its delivery is listed below). It arms again only if the cost changes, for example when you buy more.</>
        : body.watch.armed
        ? <>Watching for a give-back: best so far {money(body.watch.peak_gain)} ({pct(body.watch.peak_gain_pct)}). An alert goes out if the gain falls to +3%.</>
        : <>Not armed yet: arms once it is up 10%{body.giveback_dollar_floor_applies !== false && " and $50"}{body.watch.peak_gain != null && <> (best so far {money(body.watch.peak_gain)}, {pct(body.watch.peak_gain_pct)})</>}.</>}
    </p>}
    {body.alerts.length > 0 && <ul className="mt-1 divide-y">{body.alerts.map(a => <li key={`${a.kind}-${a.detected_at}`} className="py-2">
      <span className="font-medium">{KIND[a.kind]}</span>
      <span className="text-muted-foreground"> · {time(a.detected_at)} · {DELIVERY[a.delivery]}</span>
      <div className="text-muted-foreground">
        {a.kind === "giveback" && <>Was up {money(a.peak_gain)} ({pct(a.peak_gain_pct)}), </>}
        {a.mark != null ? <>at {money(a.gain)} ({pct(a.gain_pct)}) with {a.contracts} open</> : <>no live quote, {a.contracts} open</>}
      </div>
    </li>)}</ul>}
  </section>;
}
