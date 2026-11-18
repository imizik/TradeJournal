import { notFound, redirect } from "next/navigation";
import RadarFeedView from "@/components/RadarFeedView";
import ShadowBookView from "@/components/ShadowBookView";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

/** While the desk is home, the bare address opens the desk with the Feed on Ideas › Radar. An event (``?event=``, a
 * ping's rating link included) and ⌘K's Radar log (``?log=1``) still show this page, as does a session he picked there (``?session=``). */
export default async function RadarPage({ searchParams }: { searchParams: Promise<{ event?: string; log?: string; session?: string }> }) {
  if (!(await requireAccess()).owner) notFound();
  const { event, log, session } = await searchParams;
  if (!event && !log && !session && await api.copilotOn()) redirect("/copilot-lab?feed=radar");
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Radar</h1>
        <p className="mt-1 text-sm text-muted-foreground">Meaningful moves outside your watchlist, saved with their evidence. Phone pings only when switched on; never trading.</p>
      </div>
      <RadarFeedView />
      <ShadowBookView />
    </div>
  );
}
