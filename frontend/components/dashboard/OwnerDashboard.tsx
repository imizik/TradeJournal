import type { Account, DecisionRecord, PositionQuote, Stats, Trade } from "@/lib/api";
import type { OpenPositionRow } from "@/lib/dashboard";
import { getPositionMarketValue } from "@/lib/dashboard";
import { closedInPeriod, recentCloses, weekStart } from "@/lib/dashboardSummary";
import { money } from "@/lib/format";
import DashboardActions from "@/components/DashboardActions";
import { OpenPositionsTable, RecentClosedTable } from "@/components/DashboardTables";
import PerformanceOverview from "@/components/PerformanceOverview";
import PracticeRoutine from "@/components/PracticeRoutine";
import PracticeDecisions from "@/components/PracticeDecisions";
import DataFreshness from "./DataFreshness";
import { DashboardCard, SummaryFigure, dashboardLink, pnlTone } from "./DashboardCard";

type Params = { account?: string; type?: string; decision?: string; practice_run?: string };

/** Only the root route's owner branch mounts this command center. Data and
 * actions remain owned by the existing journal and Practice implementations. */
export default function OwnerDashboard({ trades, accounts, stats, rows, quotes, today,
  unrealized, quotedCount, grossValue, netValue, largest, decisions, params, quoteError }: {
  trades: Trade[]; accounts: Account[]; stats: Stats; rows: OpenPositionRow[];
  quotes: Record<string, PositionQuote>; today: string; unrealized: number | null;
  quotedCount: number; grossValue: number | null; netValue: number | null;
  largest: { trade: Trade; marketValue: number | null } | null;
  decisions: DecisionRecord[]; params: Params; quoteError: boolean;
}) {
  const accountMap = Object.fromEntries(accounts.map((a) => [a.id, a]));
  const accountOptions = Array.from(new Map(accounts.map((a) => [a.type, a])).values());
  const todayClosed = closedInPeriod(trades, today, today);
  const weekClosed = closedInPeriod(trades, weekStart(today), today);
  const openedToday = trades.filter((trade) => trade.opened_at.slice(0, 10) === today).length;
  const options = rows.filter(({ trade }) => trade.instrument_type === "option");
  const stocks = rows.filter(({ trade }) => trade.instrument_type !== "option");
  const coverage = (positions: OpenPositionRow[]) => `${positions.filter(({ trade, meta }) => getPositionMarketValue(trade, meta, quotes[trade.id]) != null).length} of ${positions.length} quoted`;
  const scopes = new URLSearchParams();
  if (params.account && params.account !== "all") scopes.set("account", params.account);
  if (params.type && params.type !== "all") scopes.set("type", params.type);
  const tradesHref = `/trades${scopes.size ? `?${scopes}` : ""}`;
  const analyticsScope = new URLSearchParams();
  // Analytics filters by account ID, while Dashboard scopes by account type.
  // Map only when the type identifies exactly one account; otherwise retain
  // scope on the Dashboard rather than imply a narrower analytics scope.
  const selectedAccounts = accounts.filter((account) => account.type === params.account);
  if (selectedAccounts.length === 1) analyticsScope.set("account_id", selectedAccounts[0].id);
  if (params.type && params.type !== "all") analyticsScope.set("instrument_type", params.type);
  const analyticsHref = `/analytics${analyticsScope.size ? `?${analyticsScope}` : ""}`;
  function filterHref(name: "account" | "type", value: string) {
    const search = new URLSearchParams(scopes);
    if (value === "all") search.delete(name); else search.set(name, value);
    if (params.decision) search.set("decision", params.decision);
    if (params.practice_run) search.set("practice_run", params.practice_run);
    return `/${search.size ? `?${search}` : ""}`;
  }

  return <div className="min-w-0 space-y-4" data-testid="owner-dashboard">
    <header>
      <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-xl font-semibold">Dashboard</h1><DashboardActions /></div>
      <p className="mt-1 text-sm text-muted-foreground">Your trading day, at a glance · {today} ET</p>
    </header>
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2" aria-label="Dashboard filters">
      {[{ name: "account" as const, label: "Account", choices: [{ value: "all", label: "All accounts" }, ...accountOptions.map((a) => ({ value: a.type, label: a.name }))] },
        { name: "type" as const, label: "Type", choices: [{ value: "all", label: "All types" }, { value: "option", label: "Options" }, { value: "stock", label: "Stocks" }] }].map(({ name, label, choices }) =>
        <div key={name} className="flex flex-wrap items-center gap-1" role="group" aria-label={label}>
          <span className="mr-1 text-xs text-muted-foreground">{label}</span>
          {choices.map((choice) => <a key={choice.value} href={filterHref(name, choice.value)} aria-current={(params[name] ?? "all") === choice.value ? "true" : undefined}
            className={`inline-flex min-h-11 items-center rounded-md px-2.5 text-xs sm:min-h-8 ${(params[name] ?? "all") === choice.value ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}>{choice.label}</a>)}
        </div>)}
    </div>
    <div aria-label="Journal summary" className="grid grid-cols-2 divide-x divide-border overflow-hidden rounded-lg border bg-card md:grid-cols-5">
      <SummaryFigure label="Today's Closed P&L" value={money(todayClosed.pnl, { signed: true })} tone={pnlTone(todayClosed.pnl)} detail={`${todayClosed.count} closed trades · ET`} />
      <SummaryFigure label="This Week's Closed P&L" value={money(weekClosed.pnl, { signed: true })} tone={pnlTone(weekClosed.pnl)} detail={`${weekClosed.count} closed · Mon–today ET`} />
      <SummaryFigure label="Unrealized P&L" value={money(unrealized, { signed: true })} tone={pnlTone(unrealized)} detail={`${quotedCount} of ${rows.length} positions quoted`} />
      <SummaryFigure label="Open Positions" value={String(rows.length)} detail={`${options.length} options · ${stocks.length} stock${stocks.length === 1 ? "" : "s"}`} />
      <SummaryFigure label="All-Time Closed P&L" value={money(stats.total_pnl, { signed: true })} tone={pnlTone(stats.total_pnl)} detail={`${stats.closed_trades} closed trades`} />
    </div>
    {quoteError && <p role="alert" className="rounded-md border border-amber-500/30 px-4 py-3 text-sm text-amber-300">Some position quotes could not load. Unavailable marks are shown as —. Reload to retry.</p>}
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div className="min-w-0 space-y-4">
        <DashboardCard title="Today's Session" action={<a className={dashboardLink} href={`/daily/${today}`}>Review today →</a>}>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 text-xs text-muted-foreground">
            <div>Trades opened<p className="mt-1 text-lg font-semibold tabular-nums text-foreground">{openedToday}</p></div>
            <div>Trades closed<p className="mt-1 text-lg font-semibold tabular-nums text-foreground">{todayClosed.count}</p></div>
            <div className="col-span-2"><p>{openedToday || todayClosed.count ? "Journal activity for this ET date." : "No trades opened or closed today."}</p>
              <p className="mt-1">Closed P&amp;L excludes trims of positions still open.</p>
              <a className={`${dashboardLink} mt-2`} href={tradesHref}>View trades →</a></div>
          </div>
        </DashboardCard>
        <DashboardCard title="Active Options" action={<span className="text-xs text-muted-foreground">{options.length} positions · {coverage(options)}</span>}>
          {options.length ? <OpenPositionsTable rows={options} accountMap={accountMap} quotes={quotes} today={today} compact /> : <p className="text-sm text-muted-foreground">No open options in this scope.</p>}
        </DashboardCard>
        <details className="group min-w-0 rounded-lg border bg-card" data-testid="stock-holdings">
          <summary className="flex min-h-11 cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm font-semibold">
            <span>Stock Holdings <span className="ml-1 text-muted-foreground">({stocks.length})</span></span>
            <span className="text-xs font-normal text-muted-foreground">{coverage(stocks)} · <span className="group-open:hidden">Expand</span><span className="hidden group-open:inline">Collapse</span></span>
          </summary>
          <div className="border-t p-4">{stocks.length ? <OpenPositionsTable rows={stocks} accountMap={accountMap} quotes={quotes} today={today} compact /> : <p className="text-sm text-muted-foreground">No open stocks in this scope.</p>}</div>
        </details>
        {rows.length > 0 && <details className="min-w-0 rounded-lg border bg-card">
          <summary className="min-h-11 cursor-pointer px-4 py-3 text-xs text-muted-foreground">Exposure &amp; full position details</summary>
          <div className="min-w-0 space-y-3 border-t p-4">
            <p className="text-xs text-muted-foreground">Quoted market value; option values use premium × 100. Excludes cash; not account equity or maximum loss. {quotedCount} of {rows.length} positions marked.</p>
            <dl className="grid gap-3 sm:grid-cols-3 text-xs text-muted-foreground">
              <div><dt>Gross Marked Value</dt><dd className="mt-1 font-medium tabular-nums text-foreground">{money(grossValue)}</dd></div>
              <div><dt>Net Marked Value</dt><dd className="mt-1 font-medium tabular-nums text-foreground">{money(netValue, { signed: true })}</dd></div>
              <div><dt>Largest Quoted Position</dt><dd className="mt-1 font-medium tabular-nums text-foreground">{largest ? `${largest.trade.ticker} · ${money(largest.marketValue)}` : "—"}</dd></div>
            </dl>
            <OpenPositionsTable rows={rows} accountMap={accountMap} quotes={quotes} today={today} />
          </div>
        </details>}
        <PerformanceOverview trades={trades} compact analyticsHref={analyticsHref} />
        <DashboardCard title="Recent Closed Trades" action={<a className={dashboardLink} href={tradesHref}>All trades →</a>}>
          <RecentClosedTable trades={recentCloses(trades)} accountMap={accountMap} />
        </DashboardCard>
      </div>
      <aside className="min-w-0 space-y-4" aria-label="Dashboard actions and status">
        <DataFreshness />
        <DashboardCard title="Quick Actions">
          <div className="space-y-1">
            {[{ href: "/charts", label: "Open Charts" }, { href: tradesHref, label: "View Trades" }, { href: "/daily", label: "Daily Review" }, { href: analyticsHref, label: "Explore Analytics" }].map((action) =>
              <a key={action.label} href={action.href} className="flex min-h-11 items-center justify-between rounded-md border px-3 text-xs hover:bg-secondary">{action.label}<span aria-hidden>→</span></a>)}
          </div>
          {params.account && params.account !== "all" && selectedAccounts.length !== 1 && <p className="mt-2 text-xs text-muted-foreground">Analytics opens all accounts; select the individual account there.</p>}
        </DashboardCard>
        <DashboardCard title="Daily Practice">
          <p className="text-sm tabular-nums">{decisions.length} recent saved choices</p>
          <p className="mt-1 text-xs text-muted-foreground">Practice records are separate from this journal. TAKEs require explicit paper arming.</p>
          <a href="#daily-practice" className={`${dashboardLink} mt-3`}>Open practice workspace ↓</a>
          <a href="#saved-decisions" className={`${dashboardLink} mt-2`}>Reopen saved decisions ↓</a>
        </DashboardCard>
      </aside>
    </div>
    {/* Keep every existing capability and deep link until its dedicated
        destination is complete. These components also support assigned runs. */}
    <div id="daily-practice" className="scroll-mt-4"><PracticeRoutine /></div>
    <div id="saved-decisions" className="scroll-mt-4"><PracticeDecisions records={decisions} focusId={params.decision} /></div>
  </div>;
}
