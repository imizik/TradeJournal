import ResearchStudio from "@/components/research-studio/ResearchStudio";
import { requireAccess } from "@/lib/accessServer";
export const metadata = {title: "Research Studio · Trade Journal"};
export default async function Page() {
  const access = await requireAccess();
  if (!access.owner) return <p>Research Studio requires owner access.</p>;
  return <ResearchStudio/>;
}
