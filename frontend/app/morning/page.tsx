import Link from "next/link";
import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import { newYorkToday } from "@/lib/format";
import MorningBriefing from "@/components/dashboard/MorningBriefing";

export default async function MorningPage({ searchParams }: { searchParams: Promise<{ day?: string; id?: string }> }) {
  if (!(await requireAccess()).owner) notFound();
  const params = await searchParams;
  const day = params.day && /^\d{4}-\d{2}-\d{2}$/.test(params.day) ? params.day : newYorkToday();
  return <div className="mx-auto max-w-3xl space-y-4"><Link href="/" className="inline-flex min-h-11 items-center text-sm text-primary hover:underline">← Dashboard</Link>
    <h1 className="text-xl font-semibold">Your morning with Jo</h1>
    <p className="text-sm text-muted-foreground">What deserves your attention, why it matters, and what to check next.</p>
    <MorningBriefing initialDay={day} initialId={params.id ?? null} />
  </div>;
}
