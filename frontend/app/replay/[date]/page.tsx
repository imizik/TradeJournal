import { notFound } from "next/navigation";
import ReplayView from "@/components/replay/ReplayView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function ReplayPage({ params, searchParams }: { params: Promise<{ date: string }>; searchParams: Promise<{ symbol?: string }> }) {
  if (!(await requireAccess()).owner) notFound();
  const { date } = await params;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) notFound();
  const { symbol } = await searchParams;
  return <ReplayView date={date} first={typeof symbol === "string" ? symbol.toUpperCase() : null} />;
}
