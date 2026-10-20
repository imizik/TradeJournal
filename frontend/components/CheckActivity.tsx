"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchActivity, linkActivity, unlinkActivity, type Activity, type ActivityTrade, type CheckFacts } from "@/lib/checkLinks";

// What the journal recorded after one saved check. Possible matches are only that: the owner decides what to link.
const SIDE: Record<string, string> = { buy_to_open: "Bought", sell_to_close: "Sold", sell_to_open: "Sold to open",
  buy_to_close: "Bought to close", buy: "Bought", sell: "Sold" };
const when = (seconds: number | null) => seconds == null ? "—" : new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York",
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(seconds * 1000)) + " ET";
const money = (value: number | null) => value == null ? "open" : `${value < 0 ? "−" : "+"}$${Math.abs(value).toFixed(2)}`;

function TradeLines({ trade, action, fillAction, linkedFill }: { trade: ActivityTrade; action?: React.ReactNode;
  fillAction?: (fillId: string) => React.ReactNode; linkedFill?: string | null }) {
  return <div className="space-y-1">
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <Link href={`/trades/${trade.trade_id}`} className="font-medium underline">{trade.contract}</Link>
      <span className="text-muted-foreground">{trade.account ?? "account unknown"} · {trade.status} · P&amp;L {money(trade.realized_pnl)}</span>
      {trade.timing === "same_minute" && <span className="text-xs text-muted-foreground">entered in the check&apos;s own minute; order unclear</span>}
      {action && <span className="ml-auto">{action}</span>}
    </div>
    <ul className="space-y-0.5">{trade.fills.map(f => <li key={f.fill_id} className={`flex flex-wrap items-center gap-x-2 ${linkedFill === f.fill_id ? "font-medium" : ""}`}>
      <span>{SIDE[f.side] ?? f.side} {f.contracts} @ ${f.price.toFixed(2)}</span>
      <span className="text-muted-foreground">{when(f.executed_at)}</span>
      {linkedFill === f.fill_id && <span className="text-xs">linked fill</span>}
      {fillAction?.(f.fill_id)}
    </li>)}</ul>
  </div>;
}

export default function CheckActivity({ checkId, facts }: { checkId: string; facts: CheckFacts }) {
  const [value, setValue] = useState<Activity | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify(facts);

  useEffect(() => {
    let active = true;
    fetchActivity(checkId, JSON.parse(key)).then(body => { if (active) setValue(body); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : "Journal activity unavailable."); });
    return () => { active = false; };
  }, [checkId, key]);

  const act = useCallback(async (run: () => Promise<Activity>) => {
    setBusy(true); setError("");
    try { setValue(await run()); } catch (err) { setError(err instanceof Error ? err.message : "That didn't save."); }
    finally { setBusy(false); }
  }, []);
  const button = (label: string, run: () => Promise<Activity>, small = false) =>
    <button type="button" disabled={busy} onClick={() => void act(run)}
      className={`${small ? "min-h-9 px-2 text-xs" : "min-h-11 px-3 text-sm"} rounded border disabled:opacity-50`}>{label}</button>;

  return <section aria-label="Journal afterwards" data-testid="check-activity" className="space-y-2">
    <h4 className="font-medium">Journal afterwards</h4>
    {!value && !error && <p role="status">Reading the journal…</p>}
    {error && <p role="alert" className="break-words">{error}</p>}
    {value && <>
      {value.linked.length > 0 && <div><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Linked by you</p>
        <ul className="divide-y">{value.linked.map(row => <li key={row.link_id} className="py-2" data-testid="check-linked">
          {row.trade ? <TradeLines trade={row.trade} linkedFill={row.fill_id}
            action={button("Unlink", () => unlinkActivity(checkId, facts, row.link_id))} />
            : <p className="flex flex-wrap items-center gap-2">{row.note} {button("Unlink", () => unlinkActivity(checkId, facts, row.link_id))}</p>}
        </li>)}</ul></div>}
      {value.possible.length > 0 && <div><p className="text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">Later activity — review needed</p>
        <ul className="divide-y">{value.possible.map(trade => <li key={trade.trade_id} className="py-2" data-testid="check-possible">
          <TradeLines trade={trade} action={button("Link trade", () => linkActivity(checkId, facts, { trade_id: trade.trade_id }))}
            fillAction={fillId => button("Link fill", () => linkActivity(checkId, facts, { fill_id: fillId }), true)} />
        </li>)}</ul></div>}
      {value.linked.length === 0 && value.possible.length === 0 && <p>No later activity in the journal within {value.window.days} days of this check.</p>}
      <p className="text-xs text-muted-foreground">Possible matches: same symbol, entered within {value.window.days} days after the check, in your approved accounts (Webull excluded), and the same contract where the check named one. Another account or contract can share the symbol. A match isn&apos;t proof the advice was followed or ignored; link only what you decide belongs to it. The saved advice never changes.</p>
    </>}
  </section>;
}
