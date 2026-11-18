"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";

/** Forwards parameterized ``/scanner?day=`` / ``/scanner?history=1`` visits to the desk drawer while copilot is on. */
export default function ScannerPageDeskRedirect() {
  const on = useCopilotOn();
  const router = useRouter();
  useEffect(() => {
    if (!on || window.location.pathname !== "/scanner") return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has("day") && !params.has("history")) return;
    const target = new URLSearchParams({ desk: "scanner" });
    const day = params.get("day");
    if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) target.set("day", day);
    router.replace(`/copilot-lab?${target.toString()}`);
  }, [on, router]);
  return null;
}
