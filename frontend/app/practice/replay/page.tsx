import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import PersonalReplay from "@/components/PersonalReplay";

export default async function PersonalReplayPage() {
  if (!(await requireAccess()).owner) notFound();
  return <div className="min-w-0 space-y-5">
    <header><a href="/practice" className="text-sm text-primary underline">← Daily Practice</a><h1 className="mt-2 text-2xl font-semibold">Decision Replay Lab</h1><p className="mt-1 text-sm text-muted-foreground">Make a fresh call at each frozen moment. Your choice is saved before the next moment is revealed.</p></header>
    <PersonalReplay />
  </div>;
}
