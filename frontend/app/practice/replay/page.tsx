import { notFound, redirect } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";
import PersonalReplay from "@/components/PersonalReplay";

/** Retired while the desk is home: the Decision replay lab is a line in the desk's Practice fold, so the address opens
 * the desk. With the desk off (development, the browser suite) the page still renders. */
export default async function PersonalReplayPage() {
  if (!(await requireAccess()).owner) notFound();
  if (await api.copilotOn()) redirect("/copilot-lab");
  return <div className="min-w-0 space-y-5">
    <header><a href="/practice" className="text-sm text-muted-foreground hover:text-foreground">← Daily Practice</a><h1 className="mt-3 text-xl font-semibold">Decision Replay Lab</h1><p className="mt-1 text-sm text-muted-foreground">Make a fresh call at each frozen moment. Your choice is saved before the next moment is revealed.</p></header>
    <PersonalReplay />
  </div>;
}
