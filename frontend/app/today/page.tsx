import { notFound, redirect } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

/** Today is retired: the desk shows all of it (what needs you, plans, Radar, prep, held pings, the week), so an old
 * bookmark opens the desk, or the Dashboard while the desk is off. */
export default async function TodayPage() {
  if (!(await requireAccess()).owner) notFound();
  redirect(await api.copilotOn() ? "/copilot-lab" : "/");
}
