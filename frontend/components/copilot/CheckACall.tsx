"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FIELD_LABEL, LEVELS, checkCall, checkedToday, contractWords, fieldText, passCall, planHref, type CallReading, type CheckedCall, type Level } from "@/lib/callCheck";
import { cn } from "@/lib/utils";

const FIELDS: (keyof CallReading)[] = ["ticker", "expiry", "strike", "side", "entry", "stop", "target"];
/** One quiet tone for every verdict: on the desk amber means only the strip's one next thing, and Draft is no nudge. */
const TONE: Record<string, string> = { Pass: "bg-muted text-foreground", Wait: "bg-muted text-foreground", Draft: "bg-muted text-foreground" };
const BUTTON = "inline-flex min-h-11 items-center justify-center rounded-md px-3 text-sm font-medium sm:min-h-9";
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });

/** What became of a checked call: passed, a plan saved from it, or nothing yet. */
const outcomeWords = (check: CheckedCall) => check.planned ? "plan saved" : check.outcome === "passed" ? "you passed" : null;

/** The check card: the reading as chips (blanks marked for him to set), the verdict, the tiles, Against, Changes if, then
 * Plan it (the plan flow, never a ticket) and Pass. */
function Card({ check, onPassed }: { check: CheckedCall; onPassed(next: CheckedCall): void }) {
  const [mine, setMine] = useState<Partial<Record<Level, string>>>({});
  const [passing, setPassing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const card = check.card;
  const href = planHref(check, mine);
  const pass = async () => {
    setPassing(true);
    setError(null);
    try { onPassed(await passCall(check.id)); } catch (e) { setError(e instanceof Error ? e.message : "Pass was not saved."); }
    setPassing(false);
  };
  return (
    <div data-testid="call-check-card" className="mt-3 space-y-3">
      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">What it read · blanks are yours to set</p>
        <div className="flex flex-wrap gap-1.5" data-testid="call-check-reading">
          {FIELDS.map(key => {
            const value = fieldText(check, key);
            const settable = !value && (LEVELS as readonly string[]).includes(key) && !!check.symbol;
            return (
              <span key={key} className={cn("inline-flex min-h-8 items-center gap-1 rounded-full border px-2.5 text-xs",
                value ? "bg-card" : "border-dashed border-amber-500/60 text-muted-foreground")} data-empty={value ? undefined : "true"}>
                <span className="text-muted-foreground">{FIELD_LABEL[key]}:</span>
                {value ? <b className="font-mono font-semibold text-foreground">{value}</b> : settable ? (
                  <input aria-label={`Your ${FIELD_LABEL[key].toLowerCase()}`} inputMode="decimal" placeholder="not stated · set"
                    value={mine[key as Level] ?? ""} onChange={e => setMine(m => ({ ...m, [key]: e.target.value.slice(0, 12) }))}
                    className="w-[8.5rem] bg-transparent font-mono text-foreground placeholder:text-amber-700/80 focus:outline-none dark:placeholder:text-amber-300/80" />
                ) : <span>not stated</span>}
              </span>
            );
          })}
        </div>
      </div>
      <div className="rounded-lg border bg-card p-3">
        <div className="flex items-start gap-2">
          {check.verdict && <span data-testid="call-check-verdict" className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide", TONE[check.verdict])}>{check.verdict}</span>}
          <p className="text-sm font-semibold">{card.headline}</p>
        </div>
        {card.tiles.length > 0 && (
          <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {card.tiles.map(([label, value]) => (
              <div key={label} className="rounded-md border bg-background/50 px-2 py-1.5">
                <div className="text-[11px] text-muted-foreground">{label}</div>
                <div className="font-mono text-sm font-semibold">{value}</div>
              </div>
            ))}
          </div>
        )}
        {card.against && <p className="mt-2.5 text-sm text-muted-foreground"><b className="text-foreground">Against:</b> {card.against}</p>}
        {card.changes_if && <p className="mt-1 text-sm text-muted-foreground"><b className="text-foreground">Changes if:</b> {card.changes_if}</p>}
        {card.others.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Also in the message, not checked: {card.others.join("; ")}</p>}
        {card.note && <p className="mt-1 text-xs text-muted-foreground">{card.note}</p>}
        {check.symbol && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {href && !check.planned && <Link href={href} data-testid="call-check-plan" className={cn(BUTTON, "border hover:bg-muted")}
              title="Opens the plan form with these levels as text you edit. Nothing is placed.">Plan it</Link>}
            {check.planned ? <span className="text-sm text-emerald-700 dark:text-emerald-400">Plan saved from this call.</span>
              : check.outcome === "passed" ? <span className="text-sm text-muted-foreground">Passed{check.outcome_at ? ` at ${hhmm(check.outcome_at)}` : ""}.</span>
                : <button type="button" onClick={pass} disabled={passing} data-testid="call-check-pass" className={cn(BUTTON, "border hover:bg-muted")}>Pass</button>}
            {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The desk's Check a call tab (docs/copilot-lab.md § Check a call): paste a Discord call, see what was read and the
 * copilot's card, then Plan it or Pass; the day's checked calls below, from here and from the Telegram bot alike. ``seed``
 * (the Chain tab's Check it) fills the box with a contract; nothing runs until he taps Check it.
 */
export default function CheckACall({ seed = null }: { seed?: { text: string; n: number } | null } = {}) {
  const [text, setText] = useState(seed?.text ?? "");
  useEffect(() => { if (seed) setText(seed.text); }, [seed]); // eslint-disable-line react-hooks/set-state-in-effect -- the Chain tab's Check it fills the box; he still taps Check it
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<CheckedCall | null>(null);
  const [today, setToday] = useState<CheckedCall[]>([]);
  const load = useCallback(async (signal?: AbortSignal) => {
    try { setToday(await checkedToday(signal)); } catch { /* the list stays as it was */ }
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    load(abort.signal); // eslint-disable-line react-hooks/set-state-in-effect -- the day's list, read once on open
    return () => abort.abort();
  }, [load]);
  const run = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const done = await checkCall(text.trim());
      setCurrent(done);
      setToday(list => [done, ...list.filter(c => c.id !== done.id)]);
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The check failed.");
    }
    setBusy(false);
  };
  const replace = (next: CheckedCall) => {
    setCurrent(next);
    setToday(list => list.map(c => c.id === next.id ? next : c));
  };
  return (
    <div data-testid="check-a-call" className="max-w-3xl">
      <p className="mb-2 text-sm text-muted-foreground">Paste the Discord message as it is. You see what was read with the card; anything it can&apos;t read is left blank for you, never guessed.</p>
      <textarea value={text} onChange={e => setText(e.target.value.slice(0, 2000))} rows={3} placeholder="paste here, e.g. entry: odte qqq 660 p"
        aria-label="The Discord message" onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
        className="w-full resize-y rounded-md border bg-background px-3 py-2 text-base sm:text-sm" />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" onClick={run} disabled={busy || !text.trim()} data-testid="call-check-run"
          className={cn(BUTTON, "bg-foreground text-background hover:bg-foreground/90 disabled:opacity-50")}>{busy ? "Checking…" : "Check it"}</button>
        {busy && <span className="text-xs text-muted-foreground">The copilot reads it and the prices now; this takes a few seconds.</span>}
        {error && <span role="alert" className="text-sm text-destructive">{error}</span>}
      </div>
      {current && <Card key={current.id} check={current} onPassed={replace} />}
      {today.length > 0 && <div className="mt-5">
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Checked today · {today.length}</p>
        <ul className="divide-y rounded-md border" data-testid="call-check-today">
          {today.map(check => (
            <li key={check.id}>
              <button type="button" onClick={() => setCurrent(check)} aria-current={current?.id === check.id ? "true" : undefined}
                className={cn("flex min-h-11 w-full flex-wrap items-baseline gap-x-2 px-3 py-2 text-left text-sm hover:bg-muted/50", current?.id === check.id && "bg-muted/40")}>
                <span className="font-mono text-xs text-muted-foreground">{hhmm(check.checked_at)}</span>
                <span className="font-medium">{check.symbol ? contractWords(check) : "No ticker read"}</span>
                {check.verdict && <span className={cn("rounded px-1 text-[11px] font-semibold uppercase", TONE[check.verdict])}>{check.verdict}</span>}
                {check.underlying_price != null && <span className="font-mono text-xs text-muted-foreground">{check.symbol} {check.underlying_price.toFixed(2)} then</span>}
                {outcomeWords(check) && <span className="text-xs text-muted-foreground">· {outcomeWords(check)}</span>}
                {check.source === "telegram" && <span className="text-xs text-muted-foreground">· from Telegram</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>}
      <p className="mt-3 text-xs text-muted-foreground">On your iPhone: long-press the Discord message, tap Share, then Telegram and the TradeJournal bot. The same card comes back in the chat. Every checked call is kept with the price when you checked.</p>
    </div>
  );
}
