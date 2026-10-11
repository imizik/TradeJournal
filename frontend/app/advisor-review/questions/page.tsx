import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import AdvisorAssignments from "@/components/AdvisorAssignments";

export default async function AdvisorQuestionsPage() {
  if (!(await requireAccess()).owner || process.env.TJ_ADVISOR_MANAGEMENT_ENABLED !== "true") notFound();
  return <AdvisorAssignments />;
}
