"use client";

import { useEffect, useRef, useState } from "react";
import { api, type DayJournalEntry, type DayJournalWrite } from "@/lib/api";
import { fetchChartData, type ChartData } from "@/lib/charts";
import { chartPathLink, timestampET } from "@/lib/dayJournal";
import { newYorkToday } from "@/lib/format";

const PREFIX = "SPY/QQQ morning prep";
const field = "mt-1 min-h-11 w-full rounded border bg-background px-3 py-2 text-sm";
const button = "min-h-11 rounded border px-3 text-sm hover:bg-secondary disabled:opacity-50";
type Scenario = { symbol: string; family: string; level: string; trigger: string; invalidation: string; timeStop: string };
const blank = (): Scenario => ({ symbol: "SPY", family: "Continuation", level: "", trigger: "", invalidation: "", timeStop: "" });
const kinds = ["prior_day_high", "prior_day_low", "prior_day_close", "premarket_high", "premarket_low", "overnight_high", "overnight_low"];

export default function MorningPrep({ day, onSaved }: { day: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [map, setMap] = useState<ChartData | null>(null);
  const [mapError, setMapError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [macro, setMacro] = useState("");
  const [contract, setContract] = useState("");
  const [higher, setHigher] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([blank(), { ...blank(), symbol: "QQQ", family: "Rebound / reclaim" }]);
  const [saved, setSaved] = useState<DayJournalEntry[]>([]);
  const [pending, setPending] = useState<DayJournalWrite | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [freezePlan, setFreezePlan] = useState("");
  const [freezeScenario, setFreezeScenario] = useState("1");
  const [freezeTime, setFreezeTime] = useState("");
  const [freezeNote, setFreezeNote] = useState("");
  const key = `tradejournal:morning-prep:pending:${day}`;

  useEffect(() => {
    let live = true;
    api.dayJournal(day).then((data) => { if (live) setSaved(data.entries.filter((e) => e.text.startsWith(PREFIX))); })
      .catch(() => { if (live) setMessage("Saved prep could not be loaded. Reload before making another plan."); });
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const value = JSON.parse(raw) as DayJournalWrite;
        if (typeof value.operation_id === "string" && typeof value.text === "string") {
          // eslint-disable-next-line react-hooks/set-state-in-effect
          setPending(value); setOpen(true);
        }
      }
    } catch { setMessage("Local recovery is unavailable; keep this page open until saving is confirmed."); }
    return () => { live = false; };
  }, [day, key]);

  useEffect(() => {
    if (!open || day !== newYorkToday()) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMap(null); setMapError("");
    fetchChartData({ symbol: "SPY", intervals: ["1m"], watchlist: [], session: "extended", extras: { QQQ: ["1m"] } }, controller.signal)
      .then(setMap).catch(() => { if (!controller.signal.aborted) setMapError("Levels unavailable. Open Charts or retry; do not substitute yesterday’s range."); });
    return () => controller.abort();
  }, [open, day, refresh]);

  async function save(write: DayJournalWrite) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setPending(write); setMessage("");
    try { localStorage.setItem(key, JSON.stringify(write)); } catch { setMessage("Keep this page open: local save recovery is unavailable."); }
    try {
      const entry = await api.addDayJournalEntry(day, write);
      if (entry.text.startsWith(PREFIX)) setSaved((old) => [...old.filter((e) => e.id !== entry.id), entry]);
      setPending(null);
      if (write.kind === "idea") { setFreezeTime(""); setFreezeNote(""); }
      try { localStorage.removeItem(key); } catch { /* An exact retry remains idempotent. */ }
      setMessage("Saved to your day journal. Reopen it below or in Daily Review."); onSaved();
    } catch { setMessage("Save not confirmed. Retry the unchanged save; it will not create a duplicate."); }
    finally { lock.current = false; setBusy(false); }
  }

  const valid = macro.trim() && contract.trim() && higher.trim() && scenarios.every((s) => [s.level, s.trigger, s.invalidation, s.timeStop].every((v) => v.trim()));
  function savePrep() {
    const text = [PREFIX, `Macro: ${macro}`, `Contract / size convention: ${contract}`, `Higher-timeframe levels (1–2): ${higher}`,
      ...scenarios.map((s, i) => `Scenario ${i + 1}: ${s.symbol} · ${s.family}\nLevel: ${s.level}\nTrigger: ${s.trigger}\nInvalidation: ${s.invalidation}\nTime stop: ${s.timeStop}`),
      "Owner plan; saving does not activate alerts or place an order."].join("\n\n");
    if (text.length > 5000) { setMessage("Shorten the plan to 5,000 characters before saving."); return; }
    void save({ operation_id: crypto.randomUUID(), kind: "outlook", text, not_traded: false });
  }

  return <section className="rounded-lg border bg-card p-4" aria-label="SPY and QQQ morning prep">
    <button type="button" className="flex min-h-11 w-full items-center justify-between text-left font-semibold" aria-expanded={open} onClick={() => setOpen(!open)}>
      SPY / QQQ prep <span className="text-sm font-normal text-muted-foreground">2–3 scenarios total {open ? "−" : "+"}</span>
    </button>
    {open && <div className="space-y-4 pt-3">
      <p className="text-sm text-muted-foreground">Use Jo’s market backdrop above, map the levels, then write only the setups you would take. A valid pass is not a freeze.</p>
      {day !== newYorkToday() ? <p className="text-sm text-amber-300">Historical day: live levels are not loaded. Chart links open the selected day; new notes keep today’s receipt time.</p> : <>
        <button type="button" className={button} onClick={() => setRefresh((r) => r + 1)}>Refresh levels</button>
        {!map && !mapError && <p role="status">Loading level map…</p>}
        {mapError && <p role="alert" className="text-amber-300">{mapError}</p>}
      </>}
      <div className="grid gap-3 sm:grid-cols-2">{["SPY", "QQQ"].map((symbol) => {
        const data = symbol === "SPY" ? map : map?.extras?.QQQ;
        const levels = data?.auto_levels;
        const members = Array.from(new Map((levels?.zones.flatMap((z) => z.members) ?? []).map((l) => [`${l.kind}:${l.price}`, l])).values());
        const usable = levels?.day === day;
        return <div key={symbol} className="rounded border p-3">
          <a className="inline-flex min-h-11 items-center text-primary underline" href={chartPathLink(symbol, day)}>Open {symbol} chart / alerts →</a>
          {levels && <p className="text-xs text-muted-foreground">Map for {levels.day} · calculation cutoff {timestampET(new Date(levels.as_of * 1000).toISOString())}. Refresh before acting.</p>}
          {data?.intraday_as_of && <p className="text-xs text-muted-foreground">Latest intraday data: {timestampET(new Date(data.intraday_as_of * 1000).toISOString())}</p>}
          {map?.delayed && <p className="text-xs text-amber-300">Delayed feed; confirm current price before acting.</p>}
          {usable ? <><dl className="grid grid-cols-2 gap-1 text-sm">{kinds.map((kind) => {
            const l = members.find((m) => m.kind === kind);
            return <div key={kind} className="contents"><dt>{l?.label ?? kind.replaceAll("_", " ")}</dt><dd className="text-right tabular-nums">{l ? `${l.price}${l.developing ? " · developing" : ""}` : "Unavailable"}</dd></div>;
          })}</dl><details className="mt-2 text-xs"><summary className="min-h-11 cursor-pointer py-3">Higher-timeframe candidates & sources</summary>
            {members.filter((l) => /^(prior_week|swing)_/.test(l.kind)).map((l) => <p key={`${l.kind}:${l.price}`}>{l.label}: {l.price} · {l.evidence} · {l.source ?? "source unavailable"}</p>)}
            {members.filter((l) => kinds.includes(l.kind)).map((l) => <p key={l.kind}>{l.label}: {l.source ?? "source unavailable"} · {l.evidence}</p>)}
          </details></> : <p className="text-sm text-muted-foreground">No level map for this selected day.</p>}
          {data?.issues?.map((issue) => <p key={issue} className="text-xs text-amber-300">{issue}</p>)}
          {Object.entries(levels?.missing ?? {}).map(([group, reason]) => <p key={group} className="text-xs text-amber-300">{group}: {reason}</p>)}
        </div>;
      })}</div>
      <p className="text-xs text-muted-foreground">In Charts, right-click a level to set a touch, cross or close-beyond phone alert. Choose regular hours to wait for the open. Alerts keep the price you saved; developing ranges can change. A ping is a prompt to inspect, not a trade signal.</p>
      {!!saved.length && <div className="space-y-2"><h3 className="text-sm font-medium">Saved prep</h3>{saved.map((e) => <details key={e.id} className="rounded border p-2"><summary className="min-h-11 cursor-pointer py-2">Saved {timestampET(e.created_at)}</summary><p className="whitespace-pre-wrap text-sm">{e.text}</p></details>)}</div>}
      <details open={!saved.length || !!pending}><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">{saved.length ? "Write another morning prep" : "Write morning prep"}</summary>
      <fieldset disabled={busy || !!pending} className="space-y-3 disabled:opacity-60">
        <label className="block text-sm">One-sentence macro read<input className={field} value={macro} maxLength={400} onChange={(e) => setMacro(e.target.value)} /></label>
        <label className="block text-sm">Contract / smallest-size convention<input className={field} placeholder="Your expiration, contract-selection and size rule" value={contract} maxLength={400} onChange={(e) => setContract(e.target.value)} /></label>
        <label className="block text-sm">1–2 higher-timeframe levels<input className={field} value={higher} maxLength={300} onChange={(e) => setHigher(e.target.value)} /></label>
        {scenarios.map((s, i) => <fieldset key={i} className="space-y-2 rounded border p-3"><legend className="px-1 text-sm font-medium">Scenario {i + 1}</legend>
          <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">Symbol<select aria-label={`Scenario ${i + 1} symbol`} className={field} value={s.symbol} onChange={(e) => setScenarios((old) => old.map((v, n) => n === i ? { ...v, symbol: e.target.value } : v))}><option>SPY</option><option>QQQ</option></select></label>
          <label className="text-sm">Family<select aria-label={`Scenario ${i + 1} family`} className={field} value={s.family} onChange={(e) => setScenarios((old) => old.map((v, n) => n === i ? { ...v, family: e.target.value } : v))}>{["Continuation", "Rebound / reclaim", "Rejection / fade"].map((v) => <option key={v}>{v}</option>)}</select></label></div>
          {([['level', 'Level'], ['trigger', 'Trigger'], ['invalidation', 'Invalidation'], ['timeStop', 'Time stop']] as const).map(([key, label]) => <label key={key} className="block text-sm">{label}<input aria-label={`Scenario ${i + 1} ${label.toLowerCase()}`} className={field} maxLength={250} value={s[key]} onChange={(e) => setScenarios((old) => old.map((v, n) => n === i ? { ...v, [key]: e.target.value } : v))} /></label>)}
        </fieldset>)}
        <div className="flex flex-wrap gap-2"><button type="button" className={button} onClick={() => setScenarios((s) => s.length === 2 ? [...s, { ...blank(), family: "Rejection / fade" }] : s.slice(0, 2))}>{scenarios.length === 2 ? "Add third scenario" : "Remove third scenario"}</button>
        <button type="button" className={button} disabled={!valid} onClick={savePrep}>Save morning prep</button></div>
      </fieldset>
      </details>
      <fieldset disabled={busy || !!pending} className="space-y-2 border-t pt-3"><legend className="text-sm font-medium">Log a freeze</legend>
        <p className="text-xs text-muted-foreground">Only when a planned trigger occurred and you did not take it. Record a deliberate pass or invalidation in the day journal instead.</p>
        <label className="block text-sm">Saved plan<select aria-label="Saved plan" className={field} value={freezePlan} onChange={(e) => { setFreezePlan(e.target.value); setFreezeScenario("1"); }}><option value="">Choose a saved plan</option>{saved.map((e) => <option key={e.id} value={e.id}>{timestampET(e.created_at)}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-2"><label className="text-sm">Scenario number<select aria-label="Scenario number" className={field} value={freezeScenario} onChange={(e) => setFreezeScenario(e.target.value)}>{[1, 2, 3].filter((n) => n < 3 || saved.find((e) => e.id === freezePlan)?.text.includes("Scenario 3:")).map((n) => <option key={n}>{n}</option>)}</select></label><label className="text-sm">Trigger time (ET)<input type="time" className={field} value={freezeTime} onChange={(e) => setFreezeTime(e.target.value)} /></label></div>
        <label className="block text-sm">What happened<input className={field} maxLength={500} value={freezeNote} onChange={(e) => setFreezeNote(e.target.value)} /></label>
        <button type="button" className={button} disabled={!freezePlan || !freezeTime || !freezeNote.trim()} onClick={() => void save({ operation_id: crypto.randomUUID(), kind: "idea", not_traded: true, text: `Freeze — trigger occurred; I did not take it.\nPlan entry: ${freezePlan}\nScenario ${freezeScenario} · ${day} ${freezeTime} ET (owner reported)\n${freezeNote}` })}>Save freeze</button>
      </fieldset>
      {pending && <div className="space-y-2"><p className="text-sm">Unconfirmed save; the original request is held unchanged.</p><pre className="whitespace-pre-wrap text-xs">{pending.text}</pre><button className={button} disabled={busy} onClick={() => void save(pending)}>Retry unchanged save</button></div>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </div>}
  </section>;
}
