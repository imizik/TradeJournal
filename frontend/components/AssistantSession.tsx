"use client";
import { useState } from "react";
import { useAppAccess } from "./AccessProvider";
export default function AssistantSession() {
  const { csrf, sample_data, grants } = useAppAccess();
  const [error, setError] = useState("");
  async function logout() {
    const response = await fetch("/api/access/logout", { method: "POST", headers: { "x-tj-csrf": csrf } });
    if (!response.ok) { setError("Sign-out failed. Reload and try again."); return; }
    window.location.assign("/login");
  }
  return <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">{sample_data && <strong>{grants.sample_replay ? "Simulated paper replay trial" : grants.decision_write ? "Simulated decision trial" : "Sample journal · read-only trial"}</strong>}<span>{grants.sample_replay ? "Save and replay only your own sample TAKE plans" : grants.decision_write ? "Save only your own sample decisions" : "Read-only assistant access"}</span><button onClick={logout} className="underline">Sign out</button>{error && <span role="alert">{error}</span>}</div>;
}
