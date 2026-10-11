import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import AdvisorOwnerReview from "@/components/AdvisorOwnerReview";

export default async function AdvisorReviewPage() {
  if (!(await requireAccess()).owner) notFound();
  return <AdvisorOwnerReview />;
}
