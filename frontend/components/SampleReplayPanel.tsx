"use client";

type Outcome = { entry_fill: number; exit_fill: number; net_per_share: number; planned_r: number; exit_kind: string; ambiguous: boolean; gap: boolean };
export type SampleReplay = { record_id: string; status: string; policy_version: string; policy_hash: string; tape_sha256: string; receipt_sha256: string;
  commitment_verified: boolean; outcome: Outcome | null; outcome_x3: Outcome | null;
  events: { type: string; at: number; seq: number; fill?: number; kind?: string; source: string; recorded_at: string }[] };
const money = (value: number) => `$${value.toFixed(4)}`;
export default function SampleReplayPanel({ symbol, decision, value, busy, canStart, reopened, onStart, onReopen }: {
  symbol: string; decision: string; value: SampleReplay | null; busy: boolean; canStart: boolean; reopened: boolean; onStart: () => void; onReopen: () => void;
}) {
  return <section aria-label={`${symbol} sample paper replay`} className="space-y-3 rounded border p-3 text-sm">
    <h4 className="font-semibold">Sample paper replay · {value?.status ?? "not started"}</h4>
    <p className="text-muted-foreground">Invented prices and a simulated session clock. This replay creates no broker order, journal fill, live watcher or notification.</p>
    {!value && (decision === "take" ? <><p>Start applies your frozen plan to the sealed continuation. The result is saved once and remains available after reload.</p><button type="button" disabled={busy || !canStart} onClick={onStart} className="rounded bg-primary px-3 py-2 text-primary-foreground">Start {symbol} sample replay</button>{!canStart && <p>Starting sample replays is unavailable for this login or installation.</p>}</> : <p>{decision.toUpperCase()} stays unarmed and creates no paper entry.</p>)}
    {value && <>
      <p role="status">{symbol} replay saved{reopened ? " · original replay reopened" : ""}. Frozen continuation verified.</p>
      <button type="button" disabled={busy} onClick={onReopen} className="rounded border px-3 py-2">Reopen {symbol} sample replay</button>
      <ol aria-label={`${symbol} replay timeline`} className="space-y-1">{value.events.map(event => <li key={event.seq}>Minute {(event.at / 60).toFixed(2)} · {event.type.replaceAll("_", " ")}{event.fill !== undefined ? ` · ${money(event.fill)} per share` : ""}{event.kind ? ` · ${event.kind}` : ""}</li>)}</ol>
      {value.outcome && <dl className="grid gap-2 sm:grid-cols-2"><div><dt>Sample entry per share</dt><dd>{money(value.outcome.entry_fill)}</dd></div><div><dt>Sample exit per share</dt><dd>{money(value.outcome.exit_fill)} · {value.outcome.exit_kind}</dd></div><div><dt>Net per share after sample costs</dt><dd>{money(value.outcome.net_per_share)} · {value.outcome.planned_r.toFixed(3)} planned R</dd></div>{value.outcome_x3 && <div><dt>Net per share at 3× sample costs</dt><dd>{money(value.outcome_x3.net_per_share)}</dd></div>}</dl>}
      <details><summary className="cursor-pointer">Inspect saved replay receipt</summary><p className="break-all">Decision {value.record_id} · {value.policy_version}</p><p className="break-all">Replay receipt SHA-256: {value.receipt_sha256}</p><p className="break-all">Sealed continuation SHA-256: {value.tape_sha256}</p><pre className="max-h-72 overflow-auto whitespace-pre-wrap">{JSON.stringify(value, null, 2)}</pre></details>
    </>}
  </section>;
}
