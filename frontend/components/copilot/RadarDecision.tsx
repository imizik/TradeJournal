"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, apiUrl, type DayJournalEntry, type DayJournalWrite } from "@/lib/api";
import { copilotLabHref } from "@/lib/copilot";
import { radarChoice, type RadarChoice } from "@/lib/desk";
import { planContext } from "@/components/copilot/PlanATrade";
import { UNDO_MS } from "@/components/copilot/DecisionBar";

const KIND: Record<string, string> = { relative_to_spy: "vs SPY", relative_to_sector: "vs sector" };
const BUTTON = "min-h-11 w-full rounded px-4 text-sm font-medium sm:w-auto sm:min-h-9";
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const nyDay = (at: number) => new Date(at).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const WORD: Record<RadarChoice, string> = { watching: "Watching", passing: "Passing", planning: "Planning" };

type RadarEvent = { event_id: string; session_date: string; kind: string; direction: "up" | "down"; symbols: string[]; summary: string | null; first_seen_at: string };
type Detail = { event: RadarEvent; plans: { planned: boolean; traded: boolean }; today?: boolean };

/**
 * A Radar hit opened from the desk (docs/copilot-lab.md#the-desk): what Radar saw, and one decision on it, logged as a
 * ``decision`` day-journal entry ("Watching. …", "Passing. …") after a short Undo window, or Plan it, which logs
 * "Planning. …" and opens a plan conversation that names the hit as its origin. Decisions count on the hit's own New York
 * day, the way the Radar scorecard reads them back. Advice only: nothing is placed or sized.
 */
export default function RadarDecision({ eventId, symbol, fill }: { eventId: string; symbol: string; fill(text: string): void }) {
  const router = useRouter();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [logged, setLogged] = useState<DayJournalEntry | null>(null);
  const [pending, setPending] = useState<{ choice: RadarChoice; write: DayJournalWrite } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const left = useRef<{ day: string; write: DayJournalWrite } | null>(null);
  const planning = useRef(false); // Plan it in flight: a double tap logs and navigates once

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const response = await fetch(apiUrl(`/radar/events/${encodeURIComponent(eventId)}`), { cache: "no-store", signal: controller.signal });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
      const found = body as Detail;
      const journal = await api.dayJournal(found.event.session_date);
      if (controller.signal.aborted) return;
      const seen = Date.parse(found.event.first_seen_at);
      const said = (found.event.summary ?? "").replace(/\.\s*$/, "");
      setDetail({ ...found, today: found.event.session_date === nyDay(Date.now()) });
      // This hit's own decision: its entry quotes the hit's summary, so a later hit on the symbol keeps its own.
      setLogged(journal.entries.find(e => e.kind === "decision" && e.symbol === symbol && Date.parse(e.created_at) >= seen && radarChoice(e.text)
        && (!said || e.text.includes(said))) ?? null);
    })().catch(failure => { if (!controller.signal.aborted) setFailed(failure instanceof Error ? failure.message : "Radar is unavailable."); });
    return () => controller.abort();
  }, [eventId, symbol]);

  // Leaving inside the Undo window still saves what was chosen.
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    const save = left.current;
    if (save) void fetch(apiUrl(`/day-journal/${save.day}/entries`), { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify(save.write) }).catch(() => undefined);
  }, []);

  if (failed) return <p className="mb-4 text-sm text-muted-foreground">This Radar hit could not be read: {failed}</p>;
  if (!detail) return null;
  const { event } = detail;
  const summary = (event.summary ?? `${symbol} ${event.direction}`).replace(/\.\s*$/, "");
  const kind = KIND[event.kind] ?? "Radar";
  const today = detail.today === true;
  const planHref = copilotLabHref(symbol, planContext(`Radar: ${summary}`), { kind: "radar_event", ref: event.event_id });
  const write = (choice: RadarChoice): DayJournalWrite => ({ operation_id: `decision-${uid()}`, kind: "decision", symbol, text: `${WORD[choice]}. Radar ${kind}: ${summary}.`.slice(0, 2000) });

  const send = async (next: DayJournalWrite) => {
    setError(null);
    try {
      setLogged(await api.addDayJournalEntry(event.session_date, next));
      return true;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save.");
      return false;
    }
  };
  const choose = (choice: "watching" | "passing") => {
    if (left.current) return; // a double tap logs once
    const next = { choice, write: write(choice) };
    left.current = { day: event.session_date, write: next.write };
    setPending(next);
    timer.current = setTimeout(() => {
      timer.current = null;
      left.current = null;
      void send(next.write).then(() => setPending(null));
    }, UNDO_MS);
  };
  const undo = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; left.current = null; setPending(null); };
  const plan = async () => {
    if (left.current || pending || planning.current) return;
    planning.current = true;
    if (today && !(logged && radarChoice(logged.text) === "planning") && !(await send(write("planning")))) { planning.current = false; return; }
    router.push(planHref);
  };

  const choice = logged ? radarChoice(logged.text) : null;
  return (
    <section aria-label="Radar hit" data-testid="radar-decision" className="mb-4 rounded-lg border border-primary/50 bg-card p-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <span className="font-medium text-primary">Radar · {kind}</span>
        <span>{event.direction === "up" ? "up" : "down"} · first seen {hhmm(event.first_seen_at)}{today ? "" : ` on ${event.session_date}`}</span>
        <Link href={`/radar?event=${encodeURIComponent(event.event_id)}`} className="ml-auto underline-offset-2 hover:text-foreground hover:underline">Open in Radar</Link>
      </p>
      <p className="mt-1 text-sm text-foreground">{summary}.</p>
      {detail.plans.planned && <p className="mt-1 text-xs text-muted-foreground">A plan names this hit{detail.plans.traded ? ", and it was traded" : ""}.</p>}
      {pending ? (
        <p role="status" className="mt-3 flex min-h-11 items-center gap-3 text-sm text-muted-foreground">
          Logged {pending.choice}<span aria-hidden>·</span>
          <button type="button" onClick={undo} className="min-h-11 px-1 font-medium text-foreground underline underline-offset-2 sm:min-h-0">Undo</button>
        </p>
      ) : choice && logged ? (
        <p data-testid="radar-decision-logged" className="mt-3 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
          You logged {choice} at {hhmm(logged.created_at)}.
          {choice !== "planning" && <button type="button" onClick={() => void plan()} className="min-h-11 font-medium text-foreground underline underline-offset-2 sm:min-h-0">Plan it</button>}
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          {today && <>
            <button type="button" onClick={() => choose("watching")} className={`${BUTTON} bg-primary text-primary-foreground`}>Watching</button>
            <button type="button" onClick={() => choose("passing")} className={`${BUTTON} border text-foreground hover:bg-secondary`}>Pass</button>
          </>}
          <button type="button" onClick={() => void plan()} className={`${BUTTON} border text-foreground hover:bg-secondary`}>Plan it</button>
          <button type="button" onClick={() => fill(`Radar flagged ${symbol}: ${summary}. Is it worth watching or planning, and what would make it a pass?`)}
            className="min-h-11 px-2 text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:ml-auto sm:min-h-9">
            Ask about it
          </button>
        </div>
      )}
      {!today && !choice && <p className="mt-2 text-xs text-muted-foreground">Watching or passing counts on the hit&apos;s own day.</p>}
      {error && <p role="status" className="mt-2 text-xs text-primary">Not saved: {error}. Tap again to retry.</p>}
    </section>
  );
}
