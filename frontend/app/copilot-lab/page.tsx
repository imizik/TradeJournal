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
        <p className="text-sm text-muted-foreground">Research on read-only evidence. No orders; a plan, watch or revisit exists only once you confirm it.</p>
      </div>
      <CopilotLab key={JSON.stringify(link)} link={link} />
    </div>
  );
}
