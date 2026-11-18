import { redirect } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import ScannerDayContent, { nyDate } from "@/components/ScannerDayContent";
import ScannerPageDeskRedirect from "@/components/ScannerPageDeskRedirect";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

/** While the desk is home: ``?day=`` or ``?history=1`` opens the Scanner history drawer on the desk, and the bare
 * address (or ``?symbol=``) while the scanner is on opens the desk's Feed on Ideas › Scanner. */
export default async function ScannerPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const day = typeof params.day === "string" ? params.day : undefined;
  const history = typeof params.history === "string";
  const owner = (await requireAccess()).owner;
  const copilot = owner && await api.copilotOn();
  if (copilot && (day !== undefined || history)) {
    const target = new URLSearchParams({ desk: "scanner" });
    if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) target.set("day", day);
    redirect(`/copilot-lab?${target.toString()}`);
  }
  const data = await api.scannerDay(day);
  if (data.enabled && Object.keys(params).every(key => key === "symbol") && copilot) {
    const symbol = typeof params.symbol === "string" ? params.symbol.trim().toUpperCase() : "";
    redirect(`/copilot-lab?feed=scanner${/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol) ? `&symbol=${encodeURIComponent(symbol)}` : ""}`);
  }
  const now = new Date();
  const live = data.date === nyDate(now);

  return (
    <>
      <ScannerPageDeskRedirect />
      <ScannerDayContent data={data} nowIso={now.toISOString()} live={live} />
    </>
  );
}
