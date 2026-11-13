import { redirect } from "next/navigation";
import DashboardRoute from "@/components/dashboard/DashboardRoute";
import { requireAccess } from "@/lib/accessServer";

type DashboardParams = { account?: string; type?: string; decision?: string; practice_run?: string };

/** The owner's Dashboard at its own address (under More → Journal while the desk is home). Every other viewer's
 * Dashboard stays at `/`, so this sends them there. */
export default async function DashboardPage({ searchParams }: { searchParams: Promise<DashboardParams> }) {
  if (!(await requireAccess()).owner) redirect("/");
  return <DashboardRoute searchParams={searchParams} base="/dashboard" />;
}
