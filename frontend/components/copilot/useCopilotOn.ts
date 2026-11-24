"use client";

import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { copilotStatus } from "@/lib/copilot";

/** The lab's on/off as the server layout read it for this request (null: not read there). */
const ServerRead = createContext<boolean | null>(null);
export function CopilotOnProvider({ on, children }: { on: boolean | null; children: ReactNode }) {
  return createElement(ServerRead.Provider, { value: on }, children);
}

/** True only for the owner while the lab is on. It starts from the layout's read, so the first paint already has the right
 * nav and no "off" flash, and the page's one shared status read still settles it (a failed read counts as off). */
export function useCopilotOn(): boolean {
  const { owner } = useAppAccess();
  const server = useContext(ServerRead);
  const [on, setOn] = useState(server ?? false);
  useEffect(() => {
    if (!owner) return;
    let live = true;
    copilotStatus().then(status => { if (live) setOn(status.enabled); }, () => { if (live) setOn(false); });
    return () => { live = false; };
  }, [owner]);
  return owner && on;
}
