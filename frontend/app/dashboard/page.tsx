import { redirect } from "next/navigation";
import DashboardRoute from "@/components/dashboard/DashboardRoute";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

type DashboardParams = { account?: string; type?: string; decision?: string; practice_run?: string };

/** The owner's Dashboard at its own address. While the desk is home the bare address opens the desk (the Dashboard's
 * pieces live there: Journal summary in More and ⌘K, Data sync, Plans, This week); any parameter keeps this page (a
 * filter, ``?sync=open``, a saved decision link). Every other viewer's Dashboard stays at `/`, so this sends them there. */
export default async function DashboardPage({ searchParams }: { searchParams: Promise<DashboardParams & Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) redirect("/");
  if (!Object.keys(await searchParams).length && await api.copilotOn()) redirect("/copilot-lab");
  return <DashboardRoute searchParams={searchParams} base="/dashboard" />;
}
