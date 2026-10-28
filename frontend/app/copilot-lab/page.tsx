import { IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import { notFound } from "next/navigation";
import CopilotLab from "@/components/copilot/CopilotLab";
import { requireAccess } from "@/lib/accessServer";
import { readDeepLink } from "@/lib/copilot";

export const dynamic = "force-dynamic";

// The desk's own type, ahead of the app-wide redesign (components/copilot/CopilotLab.module.css).
const sans = Instrument_Sans({ subsets: ["latin"], variable: "--desk-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--desk-mono" });

export default async function CopilotLabPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await requireAccess()).owner) notFound();
  const link = readDeepLink(await searchParams);
  return (
    // Full screen beside the nav rail on a wide screen (AppMain), the desk fills the height left under the banner.
    <div className={`${sans.variable} ${mono.variable} lg:flex lg:min-h-0 lg:flex-1 lg:flex-col`}>
      <CopilotLab key={JSON.stringify(link)} link={link} />
    </div>
  );
}
