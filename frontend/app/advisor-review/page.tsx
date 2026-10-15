import Link from "next/link";
import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import AdvisorConnectionStatus from "@/components/AdvisorConnectionStatus";
import AdvisorOwnerReview from "@/components/AdvisorOwnerReview";
import PretradeChecks from "@/components/PretradeChecks";

export default async function AdvisorReviewPage() {
  if (!(await requireAccess()).owner) notFound();
  const canManage = process.env.TJ_ADVISOR_MANAGEMENT_ENABLED === "true";
  return <>{canManage && <Link href="/advisor-review/questions" className="mb-4 inline-flex min-h-11 items-center rounded border px-3 text-sm">Manage advisor questions</Link>}<AdvisorConnectionStatus canManage={canManage} /><PretradeChecks /><AdvisorOwnerReview /></>;
}
