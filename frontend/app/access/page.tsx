import { requireAccess } from "@/lib/accessServer";
import AssistantAccess from "@/components/AssistantAccess";
import { notFound } from "next/navigation";
export default async function AccessPage() {
  const access = await requireAccess();
  if (!access.owner) notFound();
  if (!access.enabled) return <p>App authentication is not configured. The private deployment remains unchanged.</p>;
  return <AssistantAccess />;
}
