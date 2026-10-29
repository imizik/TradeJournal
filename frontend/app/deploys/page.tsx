import { notFound } from "next/navigation";
import DeploysView from "@/components/DeploysView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function DeploysPage() {
  if (!(await requireAccess()).owner) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Deploys</h1>
        <p className="text-sm text-muted-foreground">What the server runs, and what automatic deployment did recently. Refreshes every minute.</p>
      </div>
      <DeploysView />
    </div>
  );
}
