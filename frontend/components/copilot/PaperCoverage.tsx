export type Coverage = { missing: number; latest_missing_day: string | null; unknown_days: number };

export default function PaperCoverage({ coverage, unit }: { coverage?: Coverage | null; unit: string }) {
  if (!coverage?.missing && !coverage?.unknown_days) return null;
  const day = coverage.latest_missing_day;
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      {coverage.missing > 0 && <>{coverage.missing} {unit}{coverage.missing === 1 ? "" : "s"} without a receipt in the last 14 days.
        {day && <> Latest <time className="whitespace-nowrap" dateTime={day}>
          {new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" })}
        </time>.</>}
      </>}
      {coverage.unknown_days > 0 && <> Calendar coverage unavailable for {coverage.unknown_days} {coverage.unknown_days === 1 ? "day" : "days"}.</>}
    </p>
  );
}
