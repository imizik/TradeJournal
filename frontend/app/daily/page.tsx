import { api, DailyReviewIndexItem } from "@/lib/api";

function formatDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function monthLabel(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

export default async function DailyReviewPage() {
  const days = await api.dailyReviews();
  const savedCount = days.filter((day) => day.saved).length;
  const groups = groupByMonth(days);

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
        <div className="space-y-6">
          {groups.map(([month, monthDays]) => (
            <section key={month} className="space-y-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{monthLabel(monthDays[0].day)}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
                {monthDays.map((day) => (
                  <a key={day.day} href={`/daily/${day.day}`} className="rounded-lg border bg-card p-4 transition-colors hover:bg-secondary/60">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-foreground">{formatDate(day.day)}</p>
                        <p className="mt-1 text-sm text-muted-foreground">{day.trade_count} trade(s)</p>
                      </div>
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                          day.saved ? "bg-emerald-900/40 text-emerald-300" : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {day.saved ? "Saved" : "Open"}
                      </span>
                    </div>
                    {day.generated_at && (
                      <p className="mt-3 text-xs text-muted-foreground">Saved {new Date(day.generated_at).toLocaleString()}</p>
                    )}
                  </a>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

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
