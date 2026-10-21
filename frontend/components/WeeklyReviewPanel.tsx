"use client";

import { useState } from "react";
import { api, WeeklyLeak, WeeklyResult, WeeklyReview, WeeklyRuleCheck, WeeklyRuleKey, WeeklyTradeRow } from "@/lib/api";
import { mondayOf, money, newYorkToday } from "@/lib/format";

const RESULTS: { key: WeeklyResult; label: string; tone: string }[] = [
  { key: "kept", label: "Kept", tone: "border-emerald-500/60 text-emerald-300" },
  { key: "partly", label: "Partly", tone: "border-amber-500/60 text-amber-300" },
  { key: "broken", label: "Broken", tone: "border-red-500/60 text-red-300" },
  { key: "not_enough", label: "Not enough trades", tone: "border-border text-muted-foreground" },
];
const STATE = {
  kept: { label: "Kept", tone: "border-emerald-500/50 text-emerald-300" },
  broke: { label: "Broke", tone: "border-red-500/50 text-red-300" },
  unmeasured: { label: "Can't tell", tone: "border-border text-muted-foreground" },
} as const;

const dayLabel = (iso: string, year = false) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US",
  { timeZone: "UTC", month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
const when = (stamp: number | null | undefined) => stamp == null ? "" : new Date(stamp * 1000).toLocaleString("en-US",
  { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
const pnlColor = (value: number | null) => value == null ? "text-muted-foreground" : value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-muted-foreground";
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** The weekly review: last week's rule checked, this week's three exit leaks, and one rule for next week. No AI. */
export default function WeeklyReviewPanel({ initial }: { initial: WeeklyReview }) {
  const [review, setReview] = useState(initial);
  const [pick, setPick] = useState<WeeklyRuleKey | null | undefined>(initial.chosen ? initial.chosen.rule_key : undefined);
  const [note, setNote] = useState(initial.chosen?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const week = review.week_start;
  const isCurrent = week >= mondayOf(newYorkToday());

  async function save(action: () => Promise<WeeklyReview>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setReview(next);
      if (next.chosen) { setPick(next.chosen.rule_key); setNote(next.chosen.note ?? ""); }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  const leaks = new Map(review.leaks.map((leak) => [leak.key, leak]));
  const choices = [...review.rules].sort((a, b) => (leaks.get(a.key)?.pnl ?? 0) - (leaks.get(b.key)?.pnl ?? 0));
  const savedPick = review.chosen ? review.chosen.rule_key : undefined;
  const dirty = pick !== undefined && (pick !== savedPick || (note.trim() || null) !== (review.chosen?.note ?? null));

  return (
    <div className="space-y-5">
      <div>
        <a href="/daily" className="text-sm text-muted-foreground hover:text-foreground">Review Calendar</a>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="text-xl font-semibold text-foreground">Week of {dayLabel(week)} – {dayLabel(review.week_end, true)}</h1>
          <nav className="flex gap-3 text-sm" aria-label="Other weeks">
            <a href={`/daily/week/${mondayOf(week, -7)}`} className="text-blue-400 hover:text-blue-300">← Previous week</a>
            {!isCurrent && <a href={`/daily/week/${mondayOf(week, 7)}`} className="text-blue-400 hover:text-blue-300">Next week →</a>}
          </nav>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Exits are where the money leaks. Check last week&apos;s rule, then pick one rule to practise next week.
          {review.in_progress && " This week isn't over yet, so the numbers can still change."}
        </p>
      </div>

      {error && <p className="rounded border border-red-500/50 p-3 text-sm text-red-300" role="alert">{error}</p>}

      <Card title="Last week's rule">
        {!review.previous ? <p className="text-sm text-muted-foreground">No rule was chosen for this week.</p>
          : !review.previous.rule_key ? <p className="text-sm text-muted-foreground">You skipped choosing a rule for this week.</p>
          : <PreviousRule rule={review.previous.rule_text ?? ""} note={review.previous.note} check={review.previous.check!}
              result={review.previous.result} busy={busy}
              onConfirm={(result) => save(() => api.confirmWeeklyResult(week, result))} />}
      </Card>

      <Card title="This week">
        <p className="text-sm text-foreground">
          {review.summary.trades === 0 ? "No option trades closed this week."
            : <>{plural(review.summary.trades, "option trade")} closed · <span className={`font-semibold tabular-nums ${pnlColor(review.summary.pnl)}`}>
              {money(review.summary.pnl, { signed: true, cents: false })}</span> · {review.summary.wins} green, {review.summary.losses} red</>}
        </p>
      </Card>

      <Card title="Exit leaks this week">
        <ul className="divide-y divide-border">
          {review.leaks.map((leak) => <LeakRow key={leak.key} leak={leak} />)}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">A trade can appear in more than one row.</p>
      </Card>

      <Card title="Pick one rule for next week">
        {review.chosen?.result && <p className="mb-2 text-xs text-muted-foreground">This rule has already been checked, so it can&apos;t be changed.</p>}
        <fieldset className="space-y-2" disabled={busy || !!review.chosen?.result}>
          <legend className="sr-only">Rule to practise next week</legend>
          {choices.map((rule) => {
            const leak = leaks.get(rule.key);
            return (
              <Choice key={rule.key} selected={pick === rule.key} onSelect={() => setPick(rule.key)}
                title={rule.rule_text}
                detail={`${leak && leak.count ? `Cost ${money(Math.abs(leak.pnl), { cents: false })} this week (${plural(leak.count, "trade")})` : "Didn't happen this week"}${review.previous?.rule_key === rule.key ? " · last week's rule" : ""}`} />
            );
          })}
          <Choice selected={pick === null} onSelect={() => setPick(null)} title="Skip this week" detail="No rule to check next week" />
        </fieldset>
        <label className="mt-3 block text-xs text-muted-foreground">
          Note (optional)
          <input value={note} onChange={(event) => setNote(event.target.value)} maxLength={280} disabled={busy || pick === null}
            placeholder="e.g. sell half at +10%" className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground" />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" disabled={busy || !dirty || !!review.chosen?.result}
            onClick={() => save(() => api.chooseWeeklyRule(week, pick ?? null, pick ? note.trim() || null : null))}
            className="rounded bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50">
            {busy ? "Saving…" : review.chosen ? "Save change" : "Save"}
          </button>
          {review.chosen && <span className="text-xs text-muted-foreground">
            Saved {when(review.chosen.chosen_at)}: {review.chosen.rule_key ? review.chosen.rule_text : "skipped"}</span>}
        </div>
      </Card>

      {review.history.length > 0 && (
        <Card title="Rules so far">
          <ul className="space-y-1 text-sm">
            {review.history.map((row) => (
              <li key={row.week_start} className="flex flex-wrap items-baseline gap-2">
                <a href={`/daily/week/${row.week_start}`} className="w-28 shrink-0 text-xs text-blue-400 hover:text-blue-300">Week of {dayLabel(row.week_start)}</a>
                <span className="text-foreground/90">{row.label ?? "Skipped"}</span>
                {row.result && <Badge tone={RESULTS.find((r) => r.key === row.result)?.tone}>{RESULTS.find((r) => r.key === row.result)?.label}</Badge>}
                {row.rule_key && !row.result && <span className="text-xs text-muted-foreground">not checked</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Option trades in {review.coverage.accounts.join(", ") || "no account"}; Webull is excluded. {review.coverage.with_path} of {review.coverage.trades} closed{" "}
        trades have a price path; a losing trade without one is counted as &ldquo;can&apos;t tell&rdquo;, never as kept. Leaks count trades that
        closed this week; last week&apos;s rule counts trades entered after you chose it. Peaks come from minute bars and may not have been sellable.
      </p>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-4 sm:p-5" aria-label={title}>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Badge({ tone, children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${tone ?? "border-border text-muted-foreground"}`}>{children}</span>;
}

function PreviousRule({ rule, note, check, result, busy, onConfirm }: {
  rule: string; note: string | null; check: WeeklyRuleCheck; result: WeeklyResult | null; busy: boolean; onConfirm: (result: WeeklyResult) => void;
}) {
  const stillOpen = check.still_open.length;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="font-medium text-foreground">{rule}</p>
        {note && <p className="text-xs text-muted-foreground">Your note: {note}</p>}
      </div>
      <p className="text-foreground/90">
        {check.tested === 0 ? "No trade since you chose it has tested this rule yet."
          : <>{plural(check.tested, "trade")} tested it: <span className="text-emerald-300">{check.kept} kept</span>, <span className="text-red-300">{check.broke} broke</span>.</>}
        {check.unmeasured > 0 && ` ${plural(check.unmeasured, "losing trade")} can't be checked (no price path or time of day).`}
        {stillOpen > 0 && ` ${stillOpen} still open, not judged yet.`}
        {check.order_unclear > 0 && ` ${plural(check.order_unclear, "trade")} on the day you chose it has no time, so it isn't counted.`}
      </p>
      {check.trades.length > 0 && <TradeList trades={check.trades} />}
      <div>
        <p className="mb-1.5 text-xs text-muted-foreground">
          {result ? `You marked it ${RESULTS.find((r) => r.key === result)?.label.toLowerCase()}.` : "How did it go?"} Suggested from the trades: <span className="font-medium">{RESULTS.find((r) => r.key === check.suggested)?.label}</span>.
        </p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Result for last week's rule">
          {RESULTS.map((option) => (
            <button key={option.key} type="button" disabled={busy} aria-pressed={result === option.key} onClick={() => onConfirm(option.key)}
              className={`rounded border px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${result === option.key ? `${option.tone} bg-background` : "border-border text-muted-foreground hover:text-foreground"}`}>
              {option.label}{option.key === check.suggested && !result ? " (suggested)" : ""}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {check.frozen ? `Checked ${when(check.checked_at)}; these trades are kept as they were then. Trades entered later count toward the next rule.`
            : "Saving a result closes this check: trades you enter after that count toward next week's rule."}
        </p>
      </div>
    </div>
  );
}

function LeakRow({ leak }: { leak: WeeklyLeak }) {
  const summary = (
    <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <span className="font-medium text-foreground">{leak.label}</span>
      <span className="text-sm tabular-nums">
        {leak.count === 0 ? <span className="text-muted-foreground">none</span>
          : <>{plural(leak.count, "trade")} · <span className={pnlColor(leak.pnl)}>{money(leak.pnl, { signed: true, cents: false })}</span></>}
        {leak.unmeasured > 0 && <span className="text-xs text-muted-foreground"> · {leak.unmeasured} can&apos;t tell</span>}
      </span>
    </span>
  );
  return (
    <li className="py-2 text-sm">
      {leak.trades.length === 0 ? summary : (
        <details>
          <summary className="cursor-pointer list-none">{summary}</summary>
          <div className="mt-2"><TradeList trades={leak.trades} /></div>
        </details>
      )}
    </li>
  );
}

function TradeList({ trades }: { trades: WeeklyTradeRow[] }) {
  return (
    <ul className="space-y-1">
      {trades.map((row, index) => (
        <li key={`${row.trade_id ?? row.contract}-${index}`} className="flex flex-wrap items-baseline gap-2 text-xs">
          {row.state && <Badge tone={STATE[row.state].tone}>{STATE[row.state].label}</Badge>}
          {row.trade_id ? <a href={`/trades/${row.trade_id}`} className="font-medium text-blue-400 hover:text-blue-300">{row.contract}</a>
            : <span className="text-muted-foreground" title="The fill this was judged on is no longer in a trade">{row.contract} (no longer in the journal)</span>}
          <span className="text-muted-foreground">{when(row.opened_at)}</span>
          <span className={`tabular-nums ${pnlColor(row.realized_pnl)}`}>{money(row.realized_pnl, { signed: true, cents: false })}</span>
        </li>
      ))}
    </ul>
  );
}

function Choice({ selected, onSelect, title, detail }: { selected: boolean; onSelect: () => void; title: string; detail: string }) {
  return (
    <label className={`flex cursor-pointer gap-3 rounded-md border p-3 transition-colors ${selected ? "border-sky-500/60 bg-sky-500/10" : "border-border hover:border-foreground/40"}`}>
      <input type="radio" name="weekly-rule" checked={selected} onChange={onSelect} className="mt-1" />
      <span>
        <span className="block text-sm text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">{detail}</span>
      </span>
    </label>
  );
}
