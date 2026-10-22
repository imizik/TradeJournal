import { notFound } from "next/navigation";
import RadarFeedView from "@/components/RadarFeedView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function RadarPage() {
  if (!(await requireAccess()).owner) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Radar</h1>
        <p className="text-sm text-muted-foreground">Meaningful moves outside your watchlist, saved with their evidence. No alerts, no trading.</p>
      </div>
      <RadarFeedView />
    </div>
  );
}
