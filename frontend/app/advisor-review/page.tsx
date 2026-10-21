import Link from "next/link";
import { notFound } from "next/navigation";
import { accessConfig, requireAccess } from "@/lib/accessServer";
import AdvisorConnectionStatus from "@/components/AdvisorConnectionStatus";
import AdvisorOwnerReview from "@/components/AdvisorOwnerReview";
import PretradeChecks from "@/components/PretradeChecks";

export default async function AdvisorReviewPage() {
  if (!(await requireAccess()).owner) notFound();
  // The isolated invented advisor trial has its own authenticated owner entrance.
  // The normal private journal reads saved checks through its separate reader.
  if (accessConfig().profile === "private_legacy") return <>
    <h1 className="mx-auto mb-4 max-w-4xl text-xl font-semibold">Advisor review</h1>
    <PretradeChecks journal />
  </>;
  const canManage = process.env.TJ_ADVISOR_MANAGEMENT_ENABLED === "true";
  return <>{canManage && <Link href="/advisor-review/questions" className="mb-4 inline-flex min-h-11 items-center rounded border px-3 text-sm">Manage advisor questions</Link>}<AdvisorConnectionStatus canManage={canManage} /><PretradeChecks journal={accessConfig().profile === "private_legacy"} /><AdvisorOwnerReview /></>;
}
