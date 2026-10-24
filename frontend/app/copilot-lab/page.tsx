import { notFound } from "next/navigation";
import CopilotLab from "@/components/copilot/CopilotLab";
import { requireAccess } from "@/lib/accessServer";
import { readDeepLink } from "@/lib/copilot";

export const dynamic = "force-dynamic";

export default async function CopilotLabPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  const link = readDeepLink(await searchParams);
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Copilot Lab</h1>
        <p className="text-sm text-muted-foreground">An experimental research conversation with read-only evidence. No orders. A watch or a revisit it proposes is created only when you confirm it.</p>
      </div>
      <CopilotLab key={JSON.stringify(link)} link={link} />
    </div>
  );
}
