import { notFound, redirect } from "next/navigation";
import RadarFeedView from "@/components/RadarFeedView";
import ShadowBookView from "@/components/ShadowBookView";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

/** While the desk is home: bare ``/radar`` opens the desk's Feed on Ideas › Radar, and any parameter (``?event=``,
 * ``?rate=``, ``?session=``, ``?groups=``, ``?log=1``) opens the Radar log drawer on the desk (keeping phone rating links working). */
export default async function RadarPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  const params = await searchParams;
  if (await api.copilotOn()) {
    if (!Object.keys(params).length) redirect("/copilot-lab?feed=radar");
    const target = new URLSearchParams({ desk: "radar" });
    for (const key of ["event", "rate", "session", "groups"]) {
      const val = params[key];
      if (typeof val === "string" && val.trim()) target.set(key, val.trim());
    }
    redirect(`/copilot-lab?${target.toString()}`);
  }
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
