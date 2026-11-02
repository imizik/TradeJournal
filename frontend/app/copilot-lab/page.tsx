import { notFound } from "next/navigation";
import CopilotLab from "@/components/copilot/CopilotLab";
import { requireAccess } from "@/lib/accessServer";
import { readDeepLink } from "@/lib/copilot";

export const dynamic = "force-dynamic";

export default async function CopilotLabPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  const params = await searchParams;
  const link = readDeepLink(params);
  // The evening review ping's link (/copilot-lab?close=1) starts Close the day.
  const close = (Array.isArray(params.close) ? params.close[0] : params.close) === "1";
  return (
    // Full screen beside the nav rail on a wide screen (AppMain), the desk fills the height left under the banner.
    <div className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
      <CopilotLab key={JSON.stringify(link)} link={link} close={close} />
    </div>
  );
}
