"use client";

import { useState } from "react";
import AlertScorecard, { Outcome, RadarAfter } from "@/components/copilot/AlertScorecard";
import type { DeskPings, PingsRadarRow, ScorecardRow } from "@/lib/desk";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const usd = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const when = (seconds: number, day: string) => {
  const date = new Date(seconds * 1000);
  const same = date.toLocaleDateString("en-CA", { timeZone: ET }) === day;
  return date.toLocaleString("en-US", { timeZone: ET, ...(same ? {} : { weekday: "short" }), hour: "numeric", minute: "2-digit" });
};
/** "4 alerts · selling at the alert would have been better on 3, worse on 1 · 1 still open": counts only. */
export function alertsVerdict(rows: ScorecardRow[]): string | null {
  if (!rows.length) return null;
  const closed = rows.flatMap(r => r.outcome.state === "closed" ? [r.outcome.vs_alert_usd] : []);
  const better = closed.filter(v => v < 0).length, worse = closed.filter(v => v > 0).length, same = closed.filter(v => v === 0).length;
  const open = rows.filter(r => r.outcome.state === "open").length;
  const unmeasured = rows.filter(r => r.outcome.state === "not_measured").length;
  const compared = [better && `better on ${better}`, worse && `worse on ${worse}`, same && `the same on ${same}`].filter(Boolean);
  return [plural(rows.length, "alert"), compared.length ? `selling at the alert would have been ${compared.join(", ")}` : null,
    open ? `${open} still open` : null, unmeasured ? `${unmeasured} not measured` : null].filter(Boolean).join(" · ");
}

/** "2 Radar hits · 1 kept going · 1 not measured · paper: 1 of 2 setups green". */
export function radarVerdict(rows: PingsRadarRow[]): string | null {
  if (!rows.length) return null;
  const closes = rows.flatMap(r => r.after.close_pct === null ? [] : [r.after.close_pct]);
  const papers = rows.filter(r => r.paper?.state === "closed");
  return [plural(rows.length, "Radar hit"), closes.length ? `${closes.filter(v => v > 0).length} kept going` : null,
    rows.length - closes.length ? `${rows.length - closes.length} not measured` : null,
    papers.length ? `paper: ${papers.filter(r => (r.paper?.pnl ?? 0) > 0).length} of ${plural(papers.length, "setup")} green` : null,
  ].filter(Boolean).join(" · ");
}

function Paper({ row }: { row: PingsRadarRow }) {
  const paper = row.paper;
  if (!paper) return null;
  const text = paper.state === "closed" && paper.pnl !== null
    ? <>Paper <span className={cn("tabular-nums font-medium", paper.pnl > 0 ? "text-emerald-300" : paper.pnl < 0 ? "text-rose-300" : "")}>{usd(paper.pnl)}</span> a contract{paper.exit_reason ? ` (${paper.exit_reason.replace("_", " ")})` : ""}</>
    : paper.state === "open" || paper.state === "pending" ? "Paper trade still open"
      : `Paper not measured${paper.note ? `: ${paper.note}` : ""}`;
  return <span className="text-muted-foreground"> · {text}</span>;
}

/**
 * The rows under the day report's "How the pings did" line (docs/copilot-lab.md § The desk), from
 * ``GET /copilot/desk/pings?day_only=true``: each position alert (what its contracts fetched against selling at the
 * alert) and each alerted Radar hit or setup card (the stock against SPY the way Radar flagged it, and a setup's paper
 * result). Nothing to answer: counts, not advice. Last 30 days unfolds the alert and Radar scorecards.
 */
export default function PingsRows({ data }: { data: DeskPings }) {
  const [month, setMonth] = useState(false);
  const alerts = data.alerts.rows, hits = data.radar.rows;
  return (
    <div className="space-y-3 text-xs">
      {data.alerts.state === "unavailable" && <p className="text-muted-foreground">Alerts unavailable right now.</p>}
      {alerts.length > 0 && (
        <ul aria-label="Alerts" className="space-y-2">
          {alerts.map((row, i) => (
            <li key={`${row.at}-${row.contract}-${i}`} data-testid="pings-alert" className="space-y-0.5">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium text-foreground">{row.contract}</span>
                <span className="text-muted-foreground">{row.kind_label} · {when(row.at, data.day)}</span>
              </p>
              <p><Outcome row={row} /></p>
            </li>
          ))}
        </ul>
      )}
      {hits.length > 0 && (
        <ul aria-label="Radar hits" className="space-y-2">
          {hits.map(row => (
            <li key={row.event_id} data-testid="pings-hit" className="space-y-0.5">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium text-foreground">{row.symbol} {row.direction}</span>
                <span className="text-muted-foreground">{row.setup ? `Setup · ${row.kind_label}` : row.kind_label} · {when(row.at, data.day)}</span>
              </p>
              <p><RadarAfter row={row} /><Paper row={row} /></p>
            </li>
          ))}
        </ul>
      )}
      {data.radar.state === "unavailable" && <p className="text-muted-foreground">Radar unavailable right now.</p>}
      <p className="text-muted-foreground">Radar moves are the stock against SPY, the way Radar flagged it. Nothing here needs an answer.</p>
      <button type="button" aria-expanded={month} onClick={() => setMonth(open => !open)}
        className="min-h-11 text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-0">Last 30 days {month ? "▴" : "▾"}</button>
      {month && <div className="pt-1"><AlertScorecard /></div>}
    </div>
  );
}
