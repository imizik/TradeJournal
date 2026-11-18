"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api, type Account, type Stats, type Trade } from "@/lib/api";
import { closedInPeriod, recentCloses, weekStart } from "@/lib/dashboardSummary";
import { money, newYorkToday } from "@/lib/format";
import { RecentClosedTable } from "@/components/DashboardTables";
import PerformanceOverview from "@/components/PerformanceOverview";
import { SummaryFigure, dashboardLink, pnlTone } from "@/components/dashboard/DashboardCard";

/*
 * The Dashboard's journal summary and performance overview, on the desk (docs/copilot-lab.md § Retired pages): closed
 * P&L for today, this week and all time, the performance chart and the five latest closes. Opened by More → Journal
 * summary (``/copilot-lab?desk=journal``) and ⌘K's "Journal summary"; hidden until then, so the first screen is
 * unchanged. The same reads the Dashboard makes (GET /trades, /accounts, /stats), the same components. Read-only.
 */

const JOURNAL_OPEN_EVENT = "desk-journal-open";
/** Opens the desk's journal summary. */
export const openJournal = () => window.dispatchEvent(new Event(JOURNAL_OPEN_EVENT));

type Loaded = { trades: Trade[]; accounts: Account[]; stats: Stats };

export default function DeskJournal() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState(false);
  const params = useSearchParams();
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(JOURNAL_OPEN_EVENT, show);
    return () => window.removeEventListener(JOURNAL_OPEN_EVENT, show);
  }, []);
  // More → Journal summary arrives as ``?desk=journal``: it opens once and the address drops the word.
  useEffect(() => {
    if (params.get("desk") !== "journal") return;
    setOpen(true);
    const rest = new URLSearchParams(params.toString());
    rest.delete("desk");
    window.history.replaceState(null, "", `/copilot-lab${rest.size ? `?${rest}` : ""}`);
  }, [params]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    setError(false);
    Promise.all([api.trades(), api.accounts(), api.stats()])
      .then(([trades, accounts, stats]) => { if (live) setData({ trades, accounts, stats }); })
      .catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [open]);
  // Focus moves in and back out on close; Tab stays inside; Escape closes it before any desk key sees it (a native dialog
  // above, such as ⌘K, keeps its own).
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="Close journal summary"]')?.focus());
    const key = (event: KeyboardEvent) => {
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") { event.stopImmediatePropagation(); event.preventDefault(); setOpen(false); return; }
      if (event.key !== "Tab") return;
      const box = document.querySelector<HTMLElement>('[data-testid="desk-journal"]');
      const items = box ? Array.from(box.querySelectorAll<HTMLElement>("a[href], button, summary, input, [tabindex]:not([tabindex='-1'])")).filter(el => !el.hasAttribute("disabled")) : [];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!box!.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", key, true);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("keydown", key, true); if (before?.isConnected) before.focus(); };
  }, [open]);
  if (!open) return null;

  const today = newYorkToday();
  const accountMap = data ? Object.fromEntries(data.accounts.map(a => [a.id, a])) : {};
  const todayClosed = data ? closedInPeriod(data.trades, today, today) : null;
  const weekClosed = data ? closedInPeriod(data.trades, weekStart(today), today) : null;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <aside role="dialog" aria-modal="true" aria-label="Journal summary" data-testid="desk-journal"
        className="fixed right-0 top-0 z-50 flex h-screen w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">Journal summary</h2>
            <p className="mt-1 text-xs text-muted-foreground">Closed P&amp;L, performance and the latest closes · {today} ET</p>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close journal summary"
            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"><X className="h-4 w-4" /></button>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {error && <p role="alert" className="text-sm text-amber-300">The journal could not load. Close this and open it again to retry.</p>}
          {!data && !error && <p role="status" className="text-sm text-muted-foreground">Reading the journal…</p>}
          {data && todayClosed && weekClosed && <>
            <div aria-label="Journal summary figures" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-px overflow-hidden rounded-lg border bg-border">
              <SummaryFigure label="Today's Closed P&L" value={money(todayClosed.pnl, { signed: true })} tone={pnlTone(todayClosed.pnl)} detail={`${todayClosed.count} closed trades · ET`} />
              <SummaryFigure label="This Week's Closed P&L" value={money(weekClosed.pnl, { signed: true })} tone={pnlTone(weekClosed.pnl)} detail={`${weekClosed.count} closed · Mon–today ET`} />
              <SummaryFigure label="All-Time Closed P&L" value={money(data.stats.total_pnl, { signed: true })} tone={pnlTone(data.stats.total_pnl)} detail={`${data.stats.closed_trades} closed trades`} />
            </div>
            <PerformanceOverview trades={data.trades} compact />
            <section aria-label="Recent closed trades" className="min-w-0 rounded-lg border bg-card p-4">
              <div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">Recent Closed Trades</h3>
                <Link className={dashboardLink} href="/trades">All trades →</Link></div>
              <RecentClosedTable trades={recentCloses(data.trades)} accountMap={accountMap} />
            </section>
            <p className="text-xs text-muted-foreground">Filters by account and type, and the full numbers: <Link className="underline" href="/trades">Trades</Link> · <Link className="underline" href="/analytics">Analytics</Link> · <Link className="underline" href={`/daily/${today}`}>Today&apos;s review</Link>.</p>
          </>}
        </div>
      </aside>
    </>
  );
}
