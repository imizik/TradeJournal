"use client";

import { useEffect, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { copilotStatus } from "@/lib/copilot";

/** True only for the owner while the lab is on. One shared status read per page load; a failed read counts as off. */
export function useCopilotOn(): boolean {
  const { owner } = useAppAccess();
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!owner) return;
    let live = true;
    copilotStatus().then(status => { if (live) setOn(status.enabled); }, () => { if (live) setOn(false); });
    return () => { live = false; };
  }, [owner]);
  return owner && on;
}
