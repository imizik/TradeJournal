import { notFound } from "next/navigation";
import ThesesView from "@/components/ThesesView";
import { requireAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

export default async function ThesesPage() {
  if (!(await requireAccess()).owner) notFound();
  return <div className="mx-auto max-w-3xl"><ThesesView /></div>;
}
