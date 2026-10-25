import { notFound } from "next/navigation";
import PlanLinkConfirm from "@/components/PlanLinkConfirm";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What the link ping opens: confirm which saved plan this new position was, in one tap. Owner only. */
export default async function PlanLinkPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  const raw = (await searchParams).trade;
  const trade = (Array.isArray(raw) ? raw[0] : raw ?? "").trim();
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <h1 className="text-lg font-semibold text-foreground">Link your plan</h1>
      {UUID_RE.test(trade) ? <PlanLinkConfirm key={trade} tradeId={trade.toLowerCase()} />
        : <p role="alert" className="text-sm text-muted-foreground">This link names no trade. Open the trade from the journal instead.</p>}
    </div>
  );
}
