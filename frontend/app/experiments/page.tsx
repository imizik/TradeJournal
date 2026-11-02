import { notFound } from "next/navigation";
import ExperimentsView from "@/components/ExperimentsView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function ExperimentsPage() {
  if (!(await requireAccess()).owner) notFound();
  return <div className="mx-auto max-w-4xl space-y-5">
    <header className="space-y-1">
      <h1 className="text-lg font-semibold">Experiments</h1>
      <p className="text-sm text-muted-foreground">What is earning its place? Review the evidence before changing a rule.</p>
    </header>
    <ExperimentsView />
  </div>;
}
