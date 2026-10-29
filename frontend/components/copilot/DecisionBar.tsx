"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, type DayJournalEntry, type DayJournalWrite } from "@/lib/api";
import { afterClose, decisionChoice, deskDecision, reviewSkipped, savePlanDone, skipReview, type DeskActRow, type DeskDecision, type DeskThread } from "@/lib/desk";

const REFRESH_MS = 60_000;
/** Journal entries are immutable, so Undo is this window before the save is sent. */
export const UNDO_MS = 5_000;
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });

type TodayBody = { as_of: string; day: string; act_now: { state: "ok"; rows: DeskActRow[] } | { state: "unavailable" } };
type Pending = { write: DayJournalWrite; choice: DeskDecision["choice"] };
/** "Want a plan for this?": the answers, saved as the ``plan_ask`` entry's text. */
const PLAN_IT = "Planning it", NOT_NOW = "No plan for now";

const BUTTON = "min-h-11 w-full rounded px-4 text-sm font-medium sm:w-auto sm:min-h-9";

/** One save: an immutable day-journal entry, retried with the same operation id so a repeat saves once. */
function save(day: string, write: DayJournalWrite, keepalive = false) {
  if (!keepalive) return api.addDayJournalEntry(day, write);
  return fetch(apiUrl(`/day-journal/${day}/entries`), { method: "POST", keepalive, headers: { "Content-Type": "application/json" }, body: JSON.stringify(write) });
}

/**
 * The open thread's decision bar (docs/copilot-lab.md#the-desk). While the market is open and the thread's position has an
 * Act-now reason (``GET /today``), it says what fired and what the plan says, and logs Holding or Exiting as a ``decision``
 * day-journal entry after a short Undo window. After the close it asks the thread list row's close question (``close``:
 * its horizon decides whether there is one today) and saves the answer as a ``reflection``; a position with no plan is
 * asked "Want a plan for this?" once, its answer saved as a ``plan_ask`` entry, and Plan it opens planning it (``plan``).
 * An exited plan asks its one exit review at any hour: the answer is a ``reflection``, and an answer or Skip saves a
 * ``plan_done`` entry, so the plan is done and never asks again.
 * Advice only: Exiting never places, sizes or sends an order. ``fill`` puts a question in the message box, unsent.
 * ``onActive`` reports whether the bar is asking for a decision right now, so the desk can quiet the rest of the thread
 * (the plan ladder shrinks to one line while it asks). ``onReviewed`` hears the review answered or skipped, so the
 * desk's close pass can move on.
 */
export default function DecisionBar({ symbol, close = null, fill, plan, onActive, onReviewed }: {
  symbol: string | null; close?: DeskThread["close"]; fill(text: string): void; plan?(): void; onActive?(asking: boolean): void;
  onReviewed?(symbol: string): void;
}) {
  const [today, setToday] = useState<TodayBody | null>(null);
  const [entries, setEntries] = useState<DayJournalEntry[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [sending, setSending] = useState(false); // past the Undo window: the save is on its way
  const [error, setError] = useState<string | null>(null);
  const [answering, setAnswering] = useState(false);
  const [answer, setAnswer] = useState("");
  const [skipped, setSkipped] = useState(false);
  const pendingRef = useRef<{ pending: Pending; day: string } | null>(null);
  const failed = useRef<Pending | null>(null); // a save that failed is retried with its own operation id
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const read = useCallback(async (signal?: AbortSignal) => {
    if (!symbol) return;
    const response = await fetch(apiUrl("/today"), { cache: "no-store", signal });
    if (!response.ok) return;
    const body = await response.json() as TodayBody;
    const journal = await api.dayJournal(body.day);
    if (signal?.aborted) return;
    setToday(body);
    setEntries(journal.entries);
    if (afterClose(body.as_of)) setSkipped(reviewSkipped(body.day, symbol)); // no storage: the prompt shows
  }, [symbol]);

  useEffect(() => {
    const controller = new AbortController();
    const run = () => void read(controller.signal).catch(() => undefined);
    run();
    const id = setInterval(run, REFRESH_MS);
    return () => { controller.abort(); clearInterval(id); };
  }, [read]);

  // Leaving the thread inside the Undo window still saves what was chosen (the desk keys this bar by symbol).
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    const left = pendingRef.current;
    pendingRef.current = null;
    if (left) void save(left.day, left.pending.write, true).catch(() => undefined);
  }, []);

  // Asking = market hours, an Act-now reason for this symbol, and no decision logged since it fired.
  const asking = (() => {
    if (!symbol || !today || pending || afterClose(today.as_of) || today.act_now.state !== "ok") return false;
    const row = today.act_now.rows.find(r => r.symbol === symbol);
    if (!row) return false;
    const trigger = deskDecision(row).trigger;
    const logged = [...entries].reverse().find(e => e.symbol === symbol && e.kind === "decision");
    return !(logged && decisionChoice(logged.text) && !(trigger !== null && Date.parse(logged.created_at) / 1000 < trigger));
  })();
  useEffect(() => { onActive?.(asking); }, [asking, onActive]);
  useEffect(() => () => onActive?.(false), [onActive]);

  if (!symbol || !today) return null;
  const day = today.day;
  const mine = entries.filter(e => e.symbol === symbol);

  const send = async (write: DayJournalWrite) => {
    setError(null);
    try {
      const saved = await save(day, write) as DayJournalEntry;
      setEntries(current => current.some(e => e.id === saved.id) ? current : [...current, saved]);
      return true;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save.");
      return false;
    }
  };

  // ------------------------------------------------------------------ an exited plan: its one exit review, at any hour
  if (close?.kind === "exit") {
    const ended = mine.find(e => e.kind === "plan_done");
    if (ended) return <p data-testid="desk-review-done" className="text-sm text-muted-foreground">Plan done · {ended.text.toLowerCase()} at {hhmm(ended.created_at)}.</p>;
    const end = async (text: "Exit reviewed" | "Exit review skipped") => {
      try {
        const saved = await savePlanDone(symbol, text, day);
        setEntries(current => [...current, saved]);
        onReviewed?.(symbol);
      } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not save."); }
    };
    const submit = async () => {
      const text = answer.trim();
      if (!text) return;
      if (await send({ operation_id: `reflection-${uid()}`, kind: "reflection", symbol, text })) { setAnswering(false); setAnswer(""); await end("Exit reviewed"); }
    };
    return (
      <section aria-label="Exit review" data-testid="desk-review" className="rounded-lg border border-primary/40 bg-card p-3">
        <p className="text-sm font-medium text-foreground">{close.question}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">The {symbol} position is closed. Asked once: an answer or Skip marks the plan done.</p>
        {answering ? (
          <form className="mt-2 flex flex-col gap-2 sm:flex-row" onSubmit={event => { event.preventDefault(); void submit(); }}>
            <input autoFocus value={answer} onChange={event => setAnswer(event.target.value.slice(0, 2000))} aria-label={close.question}
              placeholder="Followed it or not, and the one lesson" className="min-h-11 min-w-0 flex-1 rounded border bg-background px-3 text-sm sm:min-h-9" />
            <button type="submit" disabled={!answer.trim()} className={`${BUTTON} bg-primary text-primary-foreground disabled:opacity-50`}>Save</button>
          </form>
        ) : (
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <button type="button" onClick={() => setAnswering(true)} className={`${BUTTON} bg-primary text-primary-foreground`}>Answer</button>
            <button type="button" onClick={() => void end("Exit review skipped")} className={`${BUTTON} border text-muted-foreground hover:text-foreground`}>Skip</button>
          </div>
        )}
        {error && <p role="status" className="mt-2 text-xs text-primary">Not saved: {error}</p>}
      </section>
    );
  }

  // ------------------------------------------------------------------ after the close: one review question
  if (afterClose(today.as_of)) {
    if (!close) return null;
    if (close.kind === "plan_ask") {
      const answered = mine.find(e => e.kind === "plan_ask");
      if (answered) return <p data-testid="desk-review-done" className="text-sm text-muted-foreground">{answered.text} · answered at {hhmm(answered.created_at)}.</p>;
      const choose = async (text: string) => {
        if (!await send({ operation_id: `plan-ask-${uid()}`, kind: "plan_ask", symbol, text })) return;
        onReviewed?.(symbol);
        if (text === PLAN_IT) plan?.();
      };
      return (
        <section aria-label="Close of day" data-testid="desk-review" className="rounded-lg border border-primary/40 bg-card p-3">
          <p className="text-sm font-medium text-foreground">{close.question}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{symbol} has no plan. Asked once: either answer keeps it quiet.</p>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <button type="button" onClick={() => void choose(PLAN_IT)} className={`${BUTTON} bg-primary text-primary-foreground`}>Plan it</button>
            <button type="button" onClick={() => void choose(NOT_NOW)} className={`${BUTTON} border text-muted-foreground hover:text-foreground`}>Not now</button>
          </div>
          {error && <p role="status" className="mt-2 text-xs text-primary">Not saved: {error}</p>}
        </section>
      );
    }
    const reflected = mine.find(e => e.kind === "reflection");
    if (reflected) return <p data-testid="desk-review-done" className="text-sm text-muted-foreground">You reviewed {symbol} at {hhmm(reflected.created_at)}.</p>;
    if (skipped) return null;
    const question = close.question;
    const skip = () => { setSkipped(true); skipReview(day, symbol); onReviewed?.(symbol); };
    const submit = async () => {
      const text = answer.trim();
      if (!text) return;
      if (await send({ operation_id: `reflection-${uid()}`, kind: "reflection", symbol, text })) { setAnswering(false); setAnswer(""); onReviewed?.(symbol); }
    };
    return (
      <section aria-label="Close of day" data-testid="desk-review" className="rounded-lg border border-primary/40 bg-card p-3">
        <p className="text-sm font-medium text-foreground">{question}</p>
        {answering ? (
          <form className="mt-2 flex flex-col gap-2 sm:flex-row" onSubmit={event => { event.preventDefault(); void submit(); }}>
            <input autoFocus value={answer} onChange={event => setAnswer(event.target.value.slice(0, 2000))} aria-label={question}
              placeholder="One line, in your words" className="min-h-11 min-w-0 flex-1 rounded border bg-background px-3 text-sm sm:min-h-9" />
            <button type="submit" disabled={!answer.trim()} className={`${BUTTON} bg-primary text-primary-foreground disabled:opacity-50`}>Save</button>
          </form>
        ) : (
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <button type="button" onClick={() => setAnswering(true)} className={`${BUTTON} bg-primary text-primary-foreground`}>Answer</button>
            <button type="button" onClick={skip} className={`${BUTTON} border text-muted-foreground hover:text-foreground`}>Skip</button>
          </div>
        )}
        {error && <p role="status" className="mt-2 text-xs text-primary">Not saved: {error}</p>}
      </section>
    );
  }

  // ------------------------------------------------------------------ market hours: the decision bar
  const row = today.act_now.state === "ok" ? today.act_now.rows.find(r => r.symbol === symbol) : undefined;
  if (!row) return null;
  const words = deskDecision(row);
  const logged = [...mine].reverse().find(e => e.kind === "decision");
  const loggedChoice = logged ? decisionChoice(logged.text) : null;
  // A decision logged before a later alert does not answer it.
  const stale = logged && words.trigger !== null && Date.parse(logged.created_at) / 1000 < words.trigger;

  if (pending) {
    const undo = () => { if (timer.current) clearTimeout(timer.current); pendingRef.current = null; setPending(null); };
    return (
      <p role="status" data-testid="desk-decision-pending" className="flex min-h-11 items-center gap-3 text-sm text-muted-foreground">
        Logged {pending.choice}
        {!sending && <>
          <span aria-hidden>·</span>
          <button type="button" onClick={undo} className="min-h-11 px-1 font-medium text-foreground underline underline-offset-2 sm:min-h-0">Undo</button>
        </>}
      </p>
    );
  }
  if (logged && loggedChoice && !stale) {
    return <p data-testid="desk-decision-logged" className="text-sm text-muted-foreground">{words.after(loggedChoice, hhmm(logged.created_at))}</p>;
  }

  const choose = (choice: DeskDecision["choice"]) => {
    if (pendingRef.current) return; // a double tap logs once
    const next: Pending = failed.current?.choice === choice ? failed.current
      : { choice, write: { operation_id: `decision-${uid()}`, kind: "decision", symbol, text: words.entry(choice) } };
    pendingRef.current = { pending: next, day };
    setPending(next);
    timer.current = setTimeout(() => {
      timer.current = null;
      setSending(true);
      void send(next.write).then(ok => { failed.current = ok ? null : next; pendingRef.current = null; setPending(null); setSending(false); });
    }, UNDO_MS);
  };

  return (
    <section aria-label="Decision" data-testid="desk-decision" className="rounded-lg border border-primary/50 bg-card p-3">
      <p className="text-sm font-medium text-primary">{words.fired}</p>
      {words.others.length > 0 && <p className="mt-0.5 text-xs text-muted-foreground">{words.others.join(" · ")}</p>}
      <p className="mt-1 text-sm text-foreground">{words.plan ?? "No plan on file for this position."}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <button type="button" onClick={() => choose("holding")} className={`${BUTTON} bg-primary text-primary-foreground`}>Holding</button>
        <button type="button" onClick={() => choose("exiting")} className={`${BUTTON} border text-foreground hover:bg-secondary`}>Exiting</button>
        <button type="button" onClick={() => fill(words.ask)} className="min-h-11 px-2 text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:ml-auto sm:min-h-9">
          Ask why
        </button>
      </div>
      {error && <p role="status" className="mt-2 text-xs text-primary">Not saved: {error}. Tap again to retry.</p>}
    </section>
  );
}
