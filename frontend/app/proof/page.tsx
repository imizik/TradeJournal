import { notFound } from "next/navigation";
import ProofView from "@/components/ProofView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function ProofPage() {
  if (!(await requireAccess()).owner) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Proof</h1>
        <p className="text-sm text-muted-foreground">Are position alerts and Radar earning their place? Read weekly; counts and stated rules, no grades.</p>
      </div>
      <ProofView />
    </div>
  );
}
