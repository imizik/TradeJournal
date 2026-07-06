import { WorkspaceProvider } from "@/lib/research/store";
import Cockpit from "@/components/research/Cockpit";

export const metadata = {
  title: "AI Buildout · Research",
};

export default function AiBuildoutPage() {
  return (
    <WorkspaceProvider>
      <Cockpit />
    </WorkspaceProvider>
  );
}
