"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, apiUrl, type DayJournalEntry, type DayJournalWrite } from "@/lib/api";
import { copilotLabHref } from "@/lib/copilot";
import { radarChoice, type RadarChoice } from "@/lib/desk";
import { planContext } from "@/components/copilot/PlanATrade";
import { UNDO_MS } from "@/components/copilot/DecisionBar";
import { signedDollars } from "@/components/ProofView";
import { PaperButton } from "@/components/copilot/DeskPaper";
import { contractOrder } from "@/lib/paperBook";

const KIND: Record<string, string> = { relative_to_spy: "vs SPY", relative_to_sector: "vs sector", dip_turn: "Dip turning up", gap_reversal: "Gap reversal" };
const BUTTON = "min-h-11 w-full rounded px-4 text-sm font-medium sm:w-auto sm:min-h-9";
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const nyDay = (at: number) => new Date(at).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const WORD: Record<RadarChoice, string> = { watching: "Watching", passing: "Passing", planning: "Planning" };

type RadarEvent = { event_id: string; session_date: string; kind: string; direction: "up" | "down"; symbols: string[]; summary: string | null; first_seen_at: string };
/** The event's setup card (``desk_radar_setups.view``), worded as the phone ping words it; null for an event without one. */
export type RadarSetupCard = {
  id: string; event_id: string; session_date: string; kind: string; direction: "up" | "down"; symbol: string; words: string;
  entry: number; invalidation: number; side: "below" | "above"; levels_line: string; contract_line: string | null;
  /** The candidate contract as Paper it names it, or null when there is no liquid one. */
  contract?: { option_type: "call" | "put"; expiry: string; strike: number } | null;
  record: string | null; paper_record: string | null; plan_state: "none" | "planned" | "refused"; plan_note: string | null;
  investigation_id: string | null; last: { price: number; at: string | null } | null; distance_pct: number | null;
  paper: { state: string; pnl?: number | null; exit_reason?: string | null; note?: string | null };
};
type Detail = { event: RadarEvent; plans: { planned: boolean; traded: boolean }; setup?: RadarSetupCard | null; today?: boolean };
type PlanReply = { reply: string; planned: boolean; refused: boolean; setup: RadarSetupCard };
const EXIT: Record<string, string> = { invalidation: "the invalidation", time_stop: "the 60-minute stop", session_close: "the close" };
const threadHref = (id: string) => `/copilot-lab?investigation=${encodeURIComponent(id)}`;

/** How far the latest recorded price is from the setup's invalidation, in words. */
function distanceWords(setup: RadarSetupCard): string | null {
  if (!setup.last || setup.distance_pct == null) return null;
  const at = setup.last.at ? ` at ${hhmm(setup.last.at)}` : "";
  const through = setup.direction === "up" ? setup.distance_pct <= 0 : setup.distance_pct >= 0;
  if (through) return `Last ${setup.last.price.toFixed(2)}${at}: at or through the level, so the idea is wrong now.`;
  return `Last ${setup.last.price.toFixed(2)}${at}: ${Math.abs(setup.distance_pct).toFixed(1)}% ${setup.direction === "up" ? "above" : "below"} the level.`;
}

function paperWords(setup: RadarSetupCard): string | null {
  const paper = setup.paper;
  if (paper.state === "closed" && paper.pnl != null) return `Paper result: ${signedDollars(paper.pnl)} per contract, out at ${EXIT[paper.exit_reason ?? ""] ?? paper.exit_reason}.`;
  if (paper.state === "open") return "Paper trade open.";
  if (paper.state === "pending") return "Paper trade waiting for a fresh quote.";
  if (paper.state === "unresolved") return `Paper: unresolved${paper.note ? ` (${paper.note})` : ""}.`;
  return null;
}

/** The setup card on the desk's Radar card: what the ping showed, its paper result and its plan. */
function SetupBlock({ setup, reply, paper: paperIt }: { setup: RadarSetupCard; reply: string | null; paper: boolean }) {
  const distance = distanceWords(setup);
  const paper = paperWords(setup);
  return (
    <div data-testid="radar-setup" className="mt-2 space-y-0.5 break-words rounded-md border bg-background/40 p-2 text-sm">
      <p className="font-medium text-foreground">Setup: {setup.symbol} {setup.words}</p>
      <p data-testid="radar-setup-levels" className="text-foreground">{setup.levels_line}</p>
      {distance && <p data-testid="radar-setup-distance" className="text-xs text-muted-foreground">{distance}</p>}
      <p data-testid="radar-setup-contract" className="text-foreground">{setup.contract_line ?? "No liquid contract found."}</p>
      {setup.record && <p className="text-xs text-muted-foreground">{setup.record}</p>}
      {setup.paper_record && <p className="text-xs text-muted-foreground">{setup.paper_record}</p>}
      {paper && <p data-testid="radar-setup-paper" className="text-xs text-muted-foreground">{paper}</p>}
      {paperIt && <div className="pt-1"><RadarPaperIt setup={setup} /></div>}
      {setup.plan_state === "planned" && setup.investigation_id ? (
        <p data-testid="radar-setup-planned" className="text-xs text-foreground">
          Planned{reply ? `: ${reply.replace(/^Planned [^:]+: /, "")}` : "."}{" "}
          <Link href={threadHref(setup.investigation_id)} className="inline-flex min-h-11 items-center font-medium text-primary underline-offset-2 hover:underline sm:min-h-0">Open its thread →</Link>
        </p>
      ) : setup.plan_state === "refused" ? (
        <p data-testid="radar-setup-refused" className="text-xs text-muted-foreground">Not planned: {setup.plan_note ?? "this setup was refused."}</p>
      ) : reply ? <p role="status" data-testid="radar-setup-reply" className="text-xs text-primary">{reply}</p> : null}
    </div>
  );
}

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
  const [reply, setReply] = useState<string | null>(null);
  const [closed, setClosed] = useState(false); // the server refused this setup (an earlier session): no Plan it again

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const response = await fetch(apiUrl(`/radar/events/${encodeURIComponent(eventId)}`), { cache: "no-store", signal: controller.signal });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
      const [journal, setup] = await Promise.all([api.dayJournal((body as Detail).event.session_date),
        // The event's setup card, if it has one (GET /copilot/desk/radar-setup); a failed read just leaves it out.
        fetch(apiUrl(`/copilot/desk/radar-setup?event=${encodeURIComponent(eventId)}`), { cache: "no-store", signal: controller.signal })
          .then(r => r.ok ? r.json() as Promise<{ setup: RadarSetupCard | null }> : { setup: null }).then(r => r.setup).catch(() => null)]);
      const found = { ...(body as Detail), setup };
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
  const setup = detail.setup ?? null;
  // An earlier session's card can only be refused (its level no longer applies), so an older hit keeps Plan it's
  // conversation path instead.
  const setupOpen = setup !== null && setup.plan_state === "none" && !closed && today;
  const loggedPlanning = Boolean(logged && radarChoice(logged.text) === "planning");
  // A setup card plans the way the ping's Plan it does (POST /copilot/desk/radar-setup/{id}/plan): its levels, contract, alert and
  // 60-minute check, or the same refusal. Without a card, Plan it opens a plan conversation naming the hit.
  const planSetup = async (card: RadarSetupCard) => {
    setError(null);
    setReply(null);
    try {
      const response = await fetch(apiUrl(`/copilot/desk/radar-setup/${encodeURIComponent(card.id)}/plan`), { method: "POST" });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
      const result = body as PlanReply;
      setDetail(current => current ? { ...current, setup: result.setup } : current);
      setReply(result.reply);
      if (result.refused) setClosed(true);
      if (result.planned && today && !loggedPlanning) await send(write("planning"));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not plan it.");
    }
  };
  const plan = async () => {
    if (left.current || pending || planning.current) return;
    planning.current = true;
    if (setupOpen && setup) { await planSetup(setup); planning.current = false; return; }
    if (setup && setup.plan_state === "planned") { if (today && !loggedPlanning) await send(write("planning")); planning.current = false; return; }
    if (today && !(logged && radarChoice(logged.text) === "planning") && !(await send(write("planning")))) { planning.current = false; return; }
    router.push(planHref);
  };
  // A desk plan saved while its "Planning." entry failed to log: one tap logs it again, nothing else.
  const relog = setup?.plan_state === "planned" && today && !loggedPlanning && error !== null;
  const planButton = !setup || setupOpen || relog || (!today && setup.plan_state !== "planned");

  const choice = logged ? radarChoice(logged.text) : null;
  return (
    <section aria-label="Radar hit" data-testid="radar-decision" className="mb-4 rounded-lg border border-primary/50 bg-card p-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <span className="font-medium text-primary">Radar · {kind}</span>
        <span>{event.direction === "up" ? "up" : "down"} · first seen {hhmm(event.first_seen_at)}{today ? "" : ` on ${event.session_date}`}</span>
        <Link href={`/radar?event=${encodeURIComponent(event.event_id)}`} className="ml-auto underline-offset-2 hover:text-foreground hover:underline">Open in Radar</Link>
      </p>
      <p className="mt-1 text-sm text-foreground">{summary}.</p>
      {setup && <SetupBlock setup={setup} reply={reply} paper={today} />}
      {detail.plans.planned && !(setup && setup.plan_state === "planned") && <p className="mt-1 text-xs text-muted-foreground">A plan names this hit{detail.plans.traded ? ", and it was traded" : ""}.</p>}
      {pending ? (
        <p role="status" className="mt-3 flex min-h-11 items-center gap-3 text-sm text-muted-foreground">
          Logged {pending.choice}<span aria-hidden>·</span>
          <button type="button" onClick={undo} className="min-h-11 px-1 font-medium text-foreground underline underline-offset-2 sm:min-h-0">Undo</button>
        </p>
      ) : choice && logged ? (
        <p data-testid="radar-decision-logged" className="mt-3 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
          You logged {choice} at {hhmm(logged.created_at)}.
          {(setup ? setupOpen || relog || (!today && setup.plan_state !== "planned") : choice !== "planning") && <button type="button" onClick={() => void plan()} className="min-h-11 font-medium text-foreground underline underline-offset-2 sm:min-h-0">Plan it</button>}
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          {today && <>
            <button type="button" onClick={() => choose("watching")} className={`${BUTTON} bg-primary text-primary-foreground`}>Watching</button>
            <button type="button" onClick={() => choose("passing")} className={`${BUTTON} border text-foreground hover:bg-secondary`}>Pass</button>
          </>}
          {planButton && <button type="button" onClick={() => void plan()} className={`${BUTTON} border text-foreground hover:bg-secondary`}>{relog ? "Log planning" : "Plan it"}</button>}
          <button type="button" onClick={() => fill(setup
            ? `Radar setup on ${symbol}: ${setup.words}, out ${setup.side} ${setup.invalidation.toFixed(2)}. Is it worth planning, and what would make it a pass?`
            : `Radar flagged ${symbol}: ${summary}. Is it worth watching or planning, and what would make it a pass?`)}
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

/** Paper it on a Radar setup card: its candidate contract on paper, the invalidation as the stop, recorded as Radar's idea.
 *  A card with no liquid contract says so instead. */
export function RadarPaperIt({ setup }: { setup: Pick<RadarSetupCard, "id" | "symbol" | "words" | "levels_line" | "invalidation" | "contract"> }) {
  const order = contractOrder(setup.symbol, setup.contract);
  return <PaperButton key={setup.id} order={order} why={order ? null : "No liquid contract on this card to paper."} source="radar" ideaId={setup.id}
    label="Paper it" stop={setup.invalidation} note={`Radar: ${setup.symbol} ${setup.words}. ${setup.levels_line}`} />;
}
