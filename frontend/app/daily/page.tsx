import PracticeRoutine from "@/components/PracticeRoutine";
import PracticeRunLinks from "@/components/PracticeRunLinks";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";
import type { DailyReviewIndexItem } from "@/lib/api";
import { money } from "@/lib/format";

function formatDate(value: string) {
  return new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function monthLabel(value: string) {
  return new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "long",
    year: "numeric",
  });
}

export default async function DailyReviewPage() {
  const access = await requireAccess();
  if (!access.owner && !access.grants.journal_read) return <PracticeRoutine />;
  const [days, practice] = await Promise.all([api.dailyReviews(), api.practiceRuns()]);
  const savedCount = days.filter((day) => day.saved && !day.source_data_stale).length;
  const groups = groupByMonth(days);
  // A trade dated on a weekend (an expiry or a late fill) still needs a cell: then every month shows Saturday and Sunday.
  const weekends = days.some((day) => { const { year, month, day: date } = parts(day.day); return weekday(year, month, date) > 4; });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <a href="/" className="text-sm text-muted-foreground hover:text-foreground">
            Back to Dashboard
          </a>
          <h1 className="mt-2 text-xl font-semibold text-foreground">Daily Review Calendar</h1>
          <p className="mt-1 text-sm text-muted-foreground">Pick any trading day to open or generate its saved AI review.</p>
        </div>
        <a
          href="/trades"
          className="rounded border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
        >
          All Trades
        </a>
      </div>

      <PracticeRunLinks runs={practice.runs} />
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Trade Days" value={String(days.length)} />
        <StatCard label="Saved Reviews" value={String(savedCount)} />
        <StatCard label="Need Review" value={String(days.length - savedCount)} />
      </div>

      {days.length === 0 ? (
        <section className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No trades found yet.
        </section>
      ) : (
        <div className="space-y-6" data-testid="daily-calendar">
          <Legend />
          {groups.map(([month, monthDays]) => (
            <MonthGrid key={month} month={month} days={monthDays} weekends={weekends} />
          ))}
        </div>
      )}
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** A calendar date's parts without the server's timezone moving it. */
const parts = (value: string) => { const [year, month, day] = value.split("-").map(Number); return { year, month, day }; };
/** Monday 0 … Sunday 6. */
const weekday = (year: number, month: number, day: number) => (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;

/** A day's tint: green or red by the sign of what closed, stronger with the size; neutral with nothing closed. */
function tint(pnl: number | null | undefined) {
  if (pnl == null || pnl === 0) return "bg-card";
  const size = Math.abs(pnl);
  if (pnl > 0) return size < 100 ? "bg-emerald-500/10" : size < 500 ? "bg-emerald-500/20" : size < 1500 ? "bg-emerald-500/30" : "bg-emerald-500/45";
  return size < 100 ? "bg-red-500/10" : size < 500 ? "bg-red-500/20" : size < 1500 ? "bg-red-500/30" : "bg-red-500/45";
}

const REVIEW_STATE = {
  saved: { dot: "bg-emerald-400", label: "Reviewed" },
  stale: { dot: "bg-amber-400", label: "Review needs refresh" },
  open: { dot: "", label: "Not reviewed" },
} as const;
const reviewState = (day: DailyReviewIndexItem) => day.source_data_stale ? REVIEW_STATE.stale : day.saved ? REVIEW_STATE.saved : REVIEW_STATE.open;

/**
 * One month as a Monday–Friday grid (Monday–Sunday when any trade day falls on
 * a weekend): every day has a cell so the weeks line up; a day with trades
 * links to its review and is tinted by the P&L that closed on it, with a dot
 * once it has been reviewed.
 */
function MonthGrid({ month, days, weekends }: { month: string; days: DailyReviewIndexItem[]; weekends: boolean }) {
  const columns = weekends ? 7 : 5;
  const { year, month: monthNumber } = parts(`${month}-01`);
  const byDay = new Map(days.map((day) => [parts(day.day).day, day]));
  const length = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const cells: (number | null)[] = [];
  for (let day = 1; day <= length; day++) {
    const column = weekday(year, monthNumber, day);
    if (column >= columns) continue;
    if (!cells.length) for (let pad = 0; pad < column; pad++) cells.push(null);
    cells.push(day);
  }
  const closed = days.reduce((sum, day) => sum + (day.closed_pnl ?? 0), 0);
  const anyClosed = days.some((day) => day.closed_pnl != null);

  return (
    <section className="space-y-2" aria-label={monthLabel(days[0].day)}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{monthLabel(days[0].day)}</h2>
        {anyClosed && <p className="text-xs text-muted-foreground">Closed P&amp;L <span className={`font-medium tabular-nums ${pnlColor(closed)}`}>{money(closed, { signed: true, cents: false })}</span></p>}
      </div>
      <div className={`grid gap-1.5 sm:gap-2 ${weekends ? "grid-cols-7" : "grid-cols-5"}`}>
        {WEEKDAYS.slice(0, columns).map((name) => <p key={name} className="px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{name}</p>)}
        {cells.map((dayNumber, index) => {
          if (dayNumber === null) return <div key={`pad-${index}`} />;
          const day = byDay.get(dayNumber);
          if (!day) return <div key={dayNumber} className="min-h-14 rounded-md border border-border/50 p-1.5 text-xs text-muted-foreground/50 sm:min-h-20 sm:p-2">{dayNumber}</div>;
          const state = reviewState(day);
          const trades = `${day.trade_count} trade${day.trade_count === 1 ? "" : "s"}`;
          const pnl = day.closed_pnl == null ? "nothing closed" : money(day.closed_pnl, { signed: true, cents: false });
          return (
            <a key={dayNumber} href={`/daily/${day.day}`} aria-label={`${formatDate(day.day)}: ${trades}, ${pnl}, ${state.label.toLowerCase()}`}
              title={day.generated_at ? `Saved ${new Date(day.generated_at).toLocaleString()}` : state.label}
              className={`flex min-h-14 flex-col justify-between rounded-md border p-1.5 transition-colors hover:border-foreground/40 sm:min-h-20 sm:p-2 ${tint(day.closed_pnl)}`}>
              <div className="flex items-center justify-between gap-1">
                <span className="text-xs font-semibold text-foreground">{dayNumber}</span>
                {state.dot && <span className={`h-2 w-2 shrink-0 rounded-full ${state.dot}`} aria-hidden />}
              </div>
              <div>
                <p className={`text-xs font-semibold tabular-nums sm:text-sm ${day.closed_pnl == null ? "text-muted-foreground" : pnlColor(day.closed_pnl)}`}>
                  {day.closed_pnl == null ? "—" : money(day.closed_pnl, { signed: true, cents: false })}
                </p>
                <p className="hidden text-[11px] text-muted-foreground sm:block">{trades}</p>
              </div>
            </a>
          );
        })}
      </div>
    </section>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-emerald-500/30" aria-hidden />Closed green</span>
      <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-red-500/30" aria-hidden />Closed red</span>
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden />Reviewed</span>
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-400" aria-hidden />Review needs refresh</span>
      <span>Darker means a bigger day. Click a day to open its review.</span>
    </div>
  );
}

const pnlColor = (value: number) => value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-muted-foreground";

function StatCard({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

function groupByMonth(days: DailyReviewIndexItem[]): [string, DailyReviewIndexItem[]][] {
  const grouped = new Map<string, DailyReviewIndexItem[]>();
  for (const day of days) {
    const key = day.day.slice(0, 7);
    grouped.set(key, [...(grouped.get(key) ?? []), day]);
  }
  return Array.from(grouped.entries());
}
