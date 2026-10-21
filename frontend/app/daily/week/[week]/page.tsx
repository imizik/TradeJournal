import { notFound } from "next/navigation";
import WeeklyReviewPanel from "@/components/WeeklyReviewPanel";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

/** One week's review (owner only): its exit leaks, last week's rule checked, and the rule for next week. */
export default async function WeeklyReviewPage({ params }: { params: Promise<{ week: string }> }) {
  const { week } = await params;
  const access = await requireAccess();
  if (!access.owner || !/^\d{4}-\d{2}-\d{2}$/.test(week)) notFound();
  const review = await api.weeklyReview(week).catch(() => null);
  if (!review) notFound();
  return <WeeklyReviewPanel initial={review} />;
}
