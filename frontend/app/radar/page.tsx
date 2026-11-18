import { notFound, redirect } from "next/navigation";
import RadarFeedView from "@/components/RadarFeedView";
import ShadowBookView from "@/components/ShadowBookView";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

/** While the desk is home, the bare address opens the desk with the Feed on Ideas › Radar. Any parameter keeps this page:
 * an event (``?event=``, a ping's rating link included), a session or groups view he picked here, ⌘K's Radar log (``?log=1``). */
export default async function RadarPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  if (!Object.keys(await searchParams).length && await api.copilotOn()) redirect("/copilot-lab?feed=radar");
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
