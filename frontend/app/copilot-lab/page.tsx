import { notFound } from "next/navigation";
import CopilotLab from "@/components/copilot/CopilotLab";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function CopilotLabPage() {
  if (!(await requireAccess()).owner) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Copilot Lab</h1>
        <p className="text-sm text-muted-foreground">An experimental research conversation with read-only evidence. No orders, plans, watches or alerts are saved.</p>
      </div>
      <CopilotLab />
    </div>
  );
}
