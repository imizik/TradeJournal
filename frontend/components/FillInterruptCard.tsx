"use client";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import { useAppAccess } from "./AccessProvider";

/** One fill-time pattern interrupt (backend fill_interrupts.shape). */
type Interrupt = { id: string; contract: string; kinds: string[]; title: string; lines: string[]; executed_at: number | null;
  detected_at: number; delivery: string; error: string | null; noted_at: number | null };

const time = (s: number) => `${new Date(s * 1000).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET`;

/** The interrupt a phone message opened (``?interrupt=``). ``noted`` is the message's Noted button: recorded once on
 * open (dropped from the address first, so a reload cannot repeat it); Noted on the card does the same. */
export default function FillInterruptCard({ tradeId, interruptId, noted }: { tradeId: string; interruptId: string; noted?: boolean }) {
  const { owner } = useAppAccess();
  const [row, setRow] = useState<Interrupt | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const tapped = useRef(false);

  async function note() {
    setError(null);
    try {
      const response = await fetch(apiUrl(`/trades/${encodeURIComponent(tradeId)}/fill-interrupts/${encodeURIComponent(interruptId)}/noted`), { method: "POST" });
      if (!response.ok) throw new Error();
      setRow(await response.json());
    } catch { setError("Noted could not be saved. Try again."); }
  }

  useEffect(() => {
    let active = true;
    fetch(apiUrl(`/trades/${encodeURIComponent(tradeId)}/fill-interrupts`), { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then((b: { interrupts: Interrupt[] }) => { if (active) setRow(b.interrupts.find(i => i.id === interruptId) ?? null); })
      .catch(() => { if (active) setRow(null); });
    if (noted && !tapped.current) {
      tapped.current = true;
      const url = new URL(window.location.href); url.searchParams.delete("noted");
      window.history.replaceState(window.history.state, "", url);
      void note();
    }
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for the address the page opened with
  }, [tradeId, interruptId]);

  if (row === undefined) return <p role="status" className="text-sm text-muted-foreground">Loading the message…</p>;
  if (row === null) return <p role="status" className="text-sm text-muted-foreground">This message is unavailable for this position.</p>;
  return <section aria-label="Pattern interrupt" data-testid="fill-interrupt" className="rounded-lg border border-primary/60 bg-card p-5 text-sm">
    <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pattern at your fill</h2>
    <p className="text-base font-semibold">{row.title}</p>
    <p className="text-muted-foreground">{row.contract}{row.executed_at != null && <> · filled {time(row.executed_at)}</>}</p>
    <ul className="mt-2 space-y-1">{row.lines.map(l => <li key={l}>{l}</li>)}</ul>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {row.noted_at != null ? <span role="status">Noted {time(row.noted_at)}.</span>
        : owner && <button type="button" onClick={() => void note()}
          className="inline-flex min-h-11 items-center rounded-md border px-3 font-medium hover:bg-muted">Noted</button>}
      {error && <span role="alert" className="text-amber-300">{error}</span>}
    </div>
  </section>;
}
