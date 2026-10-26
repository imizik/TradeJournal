import { notFound } from "next/navigation";
import TodayView from "@/components/today/TodayView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  if (!(await requireAccess()).owner) notFound();
  return <TodayView />;
}
