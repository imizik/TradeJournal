"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { copilotStatus } from "@/lib/copilot";

type LabState = "unknown" | "on" | "off";

/** Whether the owner's Copilot Lab is on: the same shared status read the Plans card and nav use. */
function useLabState(): LabState {
  const { owner } = useAppAccess();
  const [state, setState] = useState<LabState>(owner ? "unknown" : "off");
  useEffect(() => {
    if (!owner) return;
    let live = true;
    copilotStatus().then(status => { if (live) setState(status.enabled ? "on" : "off"); }, () => { if (live) setState("off"); });
    return () => { live = false; };
  }, [owner]);
  return state;
}

/**
 * Renders its children only while the lab is in the given state, and nothing until that is known, so a block
 * placed by it never appears and then jumps. The Dashboard uses it to show the open-options table at the top
 * while the lab is off (no Positions card then) and inside the collapsed journal while it is on.
 */
export default function WhenLab({ on, children }: { on: boolean; children: ReactNode }) {
  const state = useLabState();
  if (state === "unknown" || (state === "on") !== on) return null;
  return <>{children}</>;
}
