"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { newClientId } from "@/lib/captures";
import { listTheses, MemorySaveError, saveMemory, type MemorySave, type ThesisBoard, type ThesisRow } from "@/lib/joMorning";

/** /theses: one row per active thesis (ticker, price vs break level, next earnings, review date, the why), tapped open for
 * the full thesis, its recent pings, and a quick edit of the break level and review date or archive. Adding a thesis
 * stays in chat (the connector proposes it; the memory review accepts it). */

const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const field = "mt-1 block min-h-11 w-full rounded-md border bg-background px-3 text-base text-foreground sm:text-sm";
// A date-only value (YYYY-MM-DD) is a calendar day: read it at noon UTC so no time zone moves it a day.
const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const when = (iso: string) => new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function breakLine(row: ThesisRow) {
  if (row.break_below == null) return { text: "No break level", tone: "text-muted-foreground" };
  if (row.last == null || row.break_distance_pct == null) return { text: `Breaks under ${price(row.break_below)}`, tone: "text-muted-foreground" };
  // Breached by the prices themselves (as thesis watch decides), not the rounded percentage.
  if (row.last <= row.break_below) return { text: `Under break ${price(row.break_below)}`, tone: "text-red-400" };
  return { text: `${row.break_distance_pct.toFixed(1)}% above break ${price(row.break_below)}`, tone: row.break_distance_pct <= 5 ? "text-amber-300" : "text-muted-foreground" };
}

/** The next revision of this thesis: everything kept, only the tripwires or status changed. */
function revision(row: ThesisRow, change: { break_below?: number | null; review_on?: string | null; status: "active" | "retired" }): Omit<MemorySave, "operation_id"> {
  const b = row.body;
  return { memory_id: row.memory_id, base_revision: row.revision, kind: "thesis", symbol: row.symbol, original_text: b.original_text ?? "",
    interpretation: b.interpretation ?? null, source: b.source ?? "owner_statement", source_reference: b.source_reference ?? null,
    status: change.status, owner_confirmed: true,
    break_below: change.break_below !== undefined ? change.break_below : (b.break_below ?? null),
    review_on: change.review_on !== undefined ? change.review_on : (b.review_on ?? null) };
}

function Row({ row, today, open, onToggle, onSave, busy, error }: { row: ThesisRow; today: string; open: boolean; onToggle: () => void;
  onSave: (key: string, body: Omit<MemorySave, "operation_id">, done: string) => Promise<boolean>; busy: string | null; error?: string }) {
  const [level, setLevel] = useState(row.break_below?.toString() ?? "");
  const [review, setReview] = useState(row.review_on ?? "");
  const [confirming, setConfirming] = useState(false);
  const why = row.body.original_text ?? "";
  const brk = breakLine(row);
  const reviewDue = row.review_on != null && row.review_on <= today;
  const parsed = level.trim() === "" ? null : Number(level);
  const levelProblem = parsed != null && !(Number.isFinite(parsed) && parsed > 0 && parsed < 1_000_000) ? "Break level must be a price above zero." : null;
  const changed = parsed !== (row.break_below ?? null) || (review || null) !== (row.review_on ?? null);
  return <li data-testid="thesis-row" data-symbol={row.symbol} className="rounded-lg border bg-card">
    <button type="button" aria-expanded={open} onClick={onToggle} className="block w-full min-h-11 space-y-1 p-3 text-left">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{row.symbol}</span>
        <span className="tabular-nums text-sm">{row.last != null ? `$${price(row.last)}` : <span className="text-muted-foreground">no price</span>}{row.stale && row.last != null && <span className="text-xs text-muted-foreground"> (stale)</span>}</span>
      </div>
      <div className="flex flex-wrap justify-between gap-x-3 text-xs">
        <span className={brk.tone}>{brk.text}</span>
        <span className="text-muted-foreground">
          {row.earnings_on ? `Earnings ${day(row.earnings_on)}` : "No earnings date"}
          {" · "}
          <span className={reviewDue ? "text-amber-300" : undefined}>{row.review_on ? `Review ${day(row.review_on)}` : "No review date"}</span>
        </span>
      </div>
      <p className={open ? "whitespace-pre-wrap text-sm" : "truncate text-sm text-muted-foreground"}>{why}</p>
    </button>
    {open && <div className="space-y-3 border-t p-3">
      {row.body.interpretation && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{row.body.interpretation}</p>}
      <p className="text-xs text-muted-foreground">Saved {when(row.received_at)} ET · revision {row.revision}</p>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs text-muted-foreground">Break under<input inputMode="decimal" value={level} onChange={(e) => setLevel(e.target.value)} placeholder="none" className={field} /></label>
        <label className="text-xs text-muted-foreground">Review on<input type="date" value={review} onChange={(e) => setReview(e.target.value)} className={field} /></label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={button} disabled={!!busy || !changed || !!levelProblem}
          onClick={() => void onSave(`${row.memory_id}:edit`, revision(row, { break_below: parsed, review_on: review || null, status: "active" }), `${row.symbol} thesis updated.`)}>Save</button>
        {confirming
          ? <><button type="button" className={`${button} border-amber-500/50 text-amber-300`} disabled={!!busy}
              onClick={() => void onSave(`${row.memory_id}:archive`, revision(row, { status: "retired" }), `${row.symbol} thesis archived. It stays in memory history and no longer pings.`)}>Confirm archive</button>
            <button type="button" className={button} disabled={!!busy} onClick={() => setConfirming(false)}>Keep</button></>
          : <button type="button" className={button} disabled={!!busy} onClick={() => setConfirming(true)}>Archive</button>}
        {levelProblem && <p className="text-xs text-amber-300">{levelProblem}</p>}
      </div>
      {error && <p role="alert" className="text-sm text-amber-300">{error}</p>}
      <section aria-label={`${row.symbol} recent pings`} className="space-y-1">
        <h3 className="text-xs font-semibold text-muted-foreground">Recent thesis pings</h3>
        {!row.pings.length ? <p className="text-xs text-muted-foreground">None yet.</p>
          : <ul className="space-y-1">{row.pings.map((p, i) => <li key={`${p.fired_at}-${i}`} className="text-sm">
            <Link href={p.path} className="hover:underline">{p.text}</Link>
            <span className="block text-xs text-muted-foreground">{when(p.fired_at)} ET · {p.kind}{p.delivery !== "sent" ? ` · not sent${p.reason ? ` (${p.reason})` : ""}` : ""}</span>
          </li>)}</ul>}
      </section>
    </div>}
  </li>;
}

export default function ThesesView() {
  const [board, setBoard] = useState<ThesisBoard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // An uncertain save keeps its operation ID for an exact retry; any change to the request gets a new ID.
  const operations = useRef<Record<string, { id: string; request: string }>>({});

  useEffect(() => {
    const controller = new AbortController();
    listTheses(controller.signal).then((b) => { setBoard(b); setLoadError(null); })
      .catch((reason) => { if (!controller.signal.aborted) setLoadError((reason as Error).message); });
    return () => controller.abort();
  }, [refresh]);

  async function save(key: string, body: Omit<MemorySave, "operation_id">, done: string) {
    if (busy) return false;
    const request = JSON.stringify(body);
    if (operations.current[key]?.request !== request) operations.current[key] = { id: `owner-thesis-${newClientId()}`, request };
    setBusy(key); setNotice(null); setErrors({});
    try {
      await saveMemory({ ...body, operation_id: operations.current[key].id });
      delete operations.current[key];
      setNotice(done); setRefresh((r) => r + 1);
      return true;
    } catch (reason) {
      if (reason instanceof MemorySaveError && reason.status < 500) delete operations.current[key];
      setErrors({ [key.split(":")[0]]: (reason as Error).message }); setRefresh((r) => r + 1);
      return false;
    } finally { setBusy(null); }
  }

  return <div className="min-w-0 space-y-4 break-words" data-testid="theses">
    <header className="space-y-1">
      <h1 className="text-xl font-semibold">Theses</h1>
      <p className="text-sm text-muted-foreground">Add one in chat (“save my NBIS thesis: …, breaks under 72, review Feb 15”), then accept it in <Link href="/morning/memories" className="text-primary hover:underline">memory review</Link>.</p>
    </header>
    {board && !board.pings_on && <p className="text-xs text-muted-foreground">Break and review pings are off (THESIS_PINGS).</p>}
    {notice && <p role="status" className="text-sm text-emerald-400">{notice}</p>}
    {loadError && <p role="alert" className="text-sm text-amber-300">{loadError} <button type="button" className="underline" onClick={() => setRefresh((r) => r + 1)}>Retry</button></p>}
    {board?.issues.length ? <p className="text-xs text-amber-300">{board.issues.join("; ")}</p> : null}
    {!board && !loadError && <p role="status" className="text-sm text-muted-foreground">Loading theses…</p>}
    {board && (!board.items.length
      ? <p className="text-sm text-muted-foreground">No active theses yet.</p>
      : <ul className="space-y-2">{board.items.map((row) => <Row key={`${row.memory_id}:${row.revision}`} row={row} today={board.today} open={open === row.memory_id}
          onToggle={() => setOpen((o) => o === row.memory_id ? null : row.memory_id)} onSave={save} busy={busy} error={errors[row.memory_id]} />)}</ul>)}
  </div>;
}
