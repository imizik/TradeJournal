import Link from "next/link";
import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import PlanWatches from "@/components/dashboard/PlanWatches";

export default async function WatchesPage() {
  if (!(await requireAccess()).owner) notFound();
  return <div className="mx-auto max-w-3xl space-y-2"><Link href="/morning" className="inline-flex min-h-11 items-center text-sm text-primary hover:underline">← Morning briefing</Link>
    <PlanWatches />
  </div>;
}
