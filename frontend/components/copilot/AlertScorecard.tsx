"use client";

import { useEffect, useState } from "react";
import { getAlertScorecard, type AlertScorecard as Card, type RadarScorecard, type RadarScorecardRow, type RadarTally, type ScorecardRow, type ScorecardTally } from "@/lib/desk";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const when = (seconds: number) => new Date(seconds * 1000).toLocaleString("en-US", { timeZone: ET, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const usd = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const plain = (value: number) => `$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const tone = (value: number) => (value > 0 ? "text-emerald-300" : value < 0 ? "text-rose-300" : "text-muted-foreground");

/** "You held 5: 3 better than selling at the alert, 1 worse, 1 still open (net +$412)." Only the parts that happened. */
function held(t: ScorecardTally, verb: string) {
  if (!t.alerts) return null;
  const parts = [t.better && `${t.better} better than selling at the alert`, t.worse && `${t.worse} worse`, t.even && `${t.even} even`,
    t.open && `${t.open} still open`, t.not_measured && `${t.not_measured} not measured`].filter(Boolean);
  return { text: `You ${verb} ${t.alerts}${parts.length ? `: ${parts.join(", ")}` : ""}`, net: t.closed ? t.vs_alert_usd : null };
}

function Outcome({ row }: { row: ScorecardRow }) {
  const o = row.outcome;
  if (o.state === "not_measured") return <span className="text-muted-foreground">Not measured: {o.why}</span>;
  const basis = o.basis === "bid" ? "the alert's bid" : "the alert's mark";
  if (o.state === "open") return <span className="text-muted-foreground">Still open · {plain(o.sell_at_alert_usd)} at {basis}</span>;
  const got = o.how === "expired" ? "Expired worthless" : o.how === "sold_then_expired" ? `Sold ${plain(o.actual_usd)}, rest expired` : `Sold for ${plain(o.actual_usd)}`;
  return (
    <span>
      <span className="text-muted-foreground">{got} vs {plain(o.sell_at_alert_usd)} at {basis}: </span>
      <span className={cn("tabular-nums font-medium", tone(o.vs_alert_usd))}>{usd(o.vs_alert_usd)}</span>
    </span>
  );
}

const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
const Pct = ({ value }: { value: number }) => <span className={cn("tabular-nums font-medium", tone(value))}>{pct(value)}</span>;

/** "You watched 4 (2 kept going, avg +0.8%)": only what happened. */
function radarLine(t: RadarTally, verb: string) {
  if (!t.hits) return null;
  return <span>You {verb} {t.hits}{t.measured ? <> ({t.kept_going} kept going, avg <Pct value={t.avg_close_pct ?? 0} />)</> : null}. </span>;
}

function RadarAfter({ row }: { row: RadarScorecardRow }) {
  const { hour_pct: hour, close_pct: close, why } = row.after;
  if (hour === null && close === null) return <span className="text-muted-foreground">Not measured: {why}</span>;
  return (
    <span className="text-muted-foreground">
      {hour !== null && <>1h <Pct value={hour} /></>}{hour !== null && " · "}
      {close !== null ? <>close <Pct value={close} /></> : <>close: {why}</>}
    </span>
  );
}

/** Radar's stock hits: what was decided on each and how far the stock then went the way Radar flagged it, against SPY. */
function RadarCard({ card }: { card: RadarScorecard }) {
  const { watching, passing, planning, none } = card.summary;
  return (
    <section aria-label="Radar scorecard" className="mb-4 space-y-2 border-b pb-4 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Radar scorecard</h2>
        <span className="text-xs text-muted-foreground">last {card.window_days} days · the stock vs SPY, the way Radar flagged it, by the close</span>
      </div>
      {!card.hits ? <p className="text-muted-foreground">Radar flagged no stock in the last {card.window_days} days.</p> : (
        <>
          <p className="text-foreground">
            {card.hits} hit{card.hits === 1 ? "" : "s"}. {radarLine(watching, "watched")}{radarLine(planning, "planned")}{radarLine(passing, "passed on")}
            {none.hits > 0 && <span className="text-muted-foreground">No decision on {none.hits}{none.measured ? <> (avg <Pct value={none.avg_close_pct ?? 0} />)</> : null}.</span>}
          </p>
          <details className="group">
            <summary className="w-fit cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground">Each hit ▾</summary>
            <ul className="mt-2 space-y-2">
              {card.rows.map(row => (
                <li key={row.event_id} className="space-y-0.5">
                  <p className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium text-foreground">{row.symbol} {row.direction}</span>
                    <span className="text-xs text-muted-foreground">{row.kind_label} · {when(row.at)}</span>
                  </p>
                  <p className="text-xs">
                    <span className="text-foreground">{row.decision ? `You logged ${row.decision}` : "No decision logged"}</span>
                    {row.planned && <span className="text-muted-foreground"> · plan saved{row.traded ? ", traded" : ""}</span>}
                    <span className="text-muted-foreground"> · </span><RadarAfter row={row} />
                  </p>
                </li>
              ))}
            </ul>
            {card.truncated && <p className="mt-2 text-xs text-muted-foreground">Showing the newest {card.rows.length}.</p>}
          </details>
        </>
      )}
    </section>
  );
}

/**
 * The Briefing's alert scorecard (``GET /copilot/desk/scorecard``): for the position alerts sent to the phone in
 * the last 30 days, what was decided after each and what its contracts then fetched against selling at the alert. One
 * line, with each alert behind a disclosure. Alerts are prompts to decide, not exit rules; this is how their value shows.
 * The same read carries the Radar scorecard, shown under it while Radar records.
 */
export default function AlertScorecard() {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getAlertScorecard(controller.signal).then(setCard).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The scorecard is unavailable.");
    });
    return () => controller.abort();
  }, []);

  if (!card) return error ? <p className="mb-4 text-xs text-muted-foreground">Alert scorecard unavailable: {error}</p> : null;
  const { holding, exiting, none } = card.summary;
  const lines = [held(holding, "held"), held(exiting, "exited")].filter((line): line is NonNullable<typeof line> => line !== null);
  const radar = card.radar;
  return (
    <>
    <section aria-label="Alert scorecard" className="mb-4 space-y-2 border-b pb-4 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Alert scorecard</h2>
        <span className="text-xs text-muted-foreground">last {card.window_days} days · against selling at the alert</span>
      </div>
      {!card.alerts ? <p className="text-muted-foreground">No position alert was sent to your phone in the last {card.window_days} days.</p> : (
        <>
          <p className="text-foreground">
            {card.alerts} alert{card.alerts === 1 ? "" : "s"}.{" "}
            {lines.map((line, i) => (
              <span key={i}>{line.text}{line.net !== null && <> (net <span className={cn("tabular-nums font-medium", tone(line.net))}>{usd(line.net)}</span>)</>}. </span>
            ))}
            {none.alerts > 0 && <span className="text-muted-foreground">No decision logged on {none.alerts}.</span>}
          </p>
          <details className="group">
            <summary className="w-fit cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground">Each alert ▾</summary>
            <ul className="mt-2 space-y-2">
              {card.rows.map((row, i) => (
                <li key={`${row.at}-${row.contract}-${i}`} className="space-y-0.5">
                  <p className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium text-foreground">{row.contract}</span>
                    <span className="text-xs text-muted-foreground">{row.kind_label} · {when(row.at)}</span>
                    {row.pnl_pct_at_alert !== null && <span className="text-xs text-muted-foreground"><span className={cn("tabular-nums", tone(row.pnl_pct_at_alert))}>{row.pnl_pct_at_alert > 0 ? "+" : ""}{row.pnl_pct_at_alert}%</span> at the alert</span>}
                  </p>
                  <p className="text-xs">
                    <span className="text-foreground">{row.decision ? `You logged ${row.decision}` : "No decision logged"}</span>
                    <span className="text-muted-foreground"> · </span><Outcome row={row} />
                  </p>
                </li>
              ))}
            </ul>
            {card.truncated && <p className="mt-2 text-xs text-muted-foreground">Showing the newest {card.rows.length}.</p>}
          </details>
        </>
      )}
    </section>
    {radar?.state === "ok" ? <RadarCard card={radar} />
      : radar?.state === "unavailable" && <p className="mb-4 text-xs text-muted-foreground">Radar scorecard unavailable: {radar.reason}</p>}
    </>
  );
}
