import { notFound } from "next/navigation";
import MonthlyAiPanel from "@/components/MonthlyAiPanel";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

function monthLabel(month: string) {
  return new Date(`${month}-15T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "long", year: "numeric" });
}

/** One month's review (owner only): its saved review, or the button to write one. */
export default async function MonthlyReviewPage({ params }: { params: Promise<{ month: string }> }) {
  const { month } = await params;
  const access = await requireAccess();
  if (!access.owner || !/^\d{4}-\d{2}$/.test(month)) notFound();
  const [months, saved] = await Promise.all([api.monthlyReviews(), api.monthlyReview(month)]);
  const row = months.find((item) => item.month === month);
  if (!row) notFound();
  return (
    <div className="space-y-6">
      <div>
        <a href="/daily" className="text-sm text-muted-foreground hover:text-foreground">Review Calendar</a>
        <h1 className="mt-2 text-xl font-semibold text-foreground">{monthLabel(month)}</h1>
      </div>
      <MonthlyAiPanel month={month} monthLabel={monthLabel(month)} closedTrades={row.closed_trades}
        initialReview={saved?.review ?? null} initialGeneratedAt={saved?.generated_at ?? null} />
    </div>
  );
}
