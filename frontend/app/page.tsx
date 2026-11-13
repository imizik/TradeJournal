import { redirect } from "next/navigation";
import DashboardRoute from "@/components/dashboard/DashboardRoute";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";

type HomeParams = { account?: string; type?: string; decision?: string; practice_run?: string; sync?: string; job?: string };

/**
 * Home. While the Copilot Lab is on, the owner's home is the desk (`/copilot-lab`): `/` (and the installed phone app's
 * start URL) lands there, and the Dashboard lives at `/dashboard`. An old Dashboard address with a filter or the Sync
 * Center opener goes to `/dashboard` with it; a saved practice link still opens Daily Practice (DashboardRoute). Every
 * other viewer, and the owner while the lab is off, gets the Dashboard here exactly as before.
 */
export default async function HomePage({ searchParams }: { searchParams: Promise<HomeParams> }) {
  const access = await requireAccess();
  if (access.owner) {
    const params = await searchParams;
    if (!params.decision && !params.practice_run && await api.copilotOn()) {
      const rest = new URLSearchParams(Object.entries(params).filter((entry): entry is [string, string] => typeof entry[1] === "string"));
      redirect(rest.size ? `/dashboard?${rest}` : "/copilot-lab");
    }
  }
  return <DashboardRoute searchParams={searchParams} />;
}
