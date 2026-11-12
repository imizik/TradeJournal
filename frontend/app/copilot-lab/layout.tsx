import type { ReactNode } from "react";
import { DeskMemory } from "@/components/copilot/DeskMemory";

// The desk's reads are kept in memory across its remounts (a deep link, Plan a trade) for as long as the owner stays on
// the desk; leaving /copilot-lab drops them.
export default function CopilotLabLayout({ children }: { children: ReactNode }) {
  return <DeskMemory>{children}</DeskMemory>;
}
