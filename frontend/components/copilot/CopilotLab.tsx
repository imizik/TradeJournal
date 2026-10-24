"use client";

import CopilotPanel, { type PanelLink } from "@/components/copilot/CopilotPanel";

/** The full-page Copilot Lab: the same conversation as the side panels, with Recent, the symbol and deep links. */
export default function CopilotLab({ link = null }: { link?: PanelLink | null }) {
  return <CopilotPanel variant="page" link={link} />;
}
