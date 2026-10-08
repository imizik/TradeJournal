"use client";
import { useState } from "react";
import { useAppAccess } from "./AccessProvider";
export default function AssistantSession() {
  const { csrf } = useAppAccess();
  const [error, setError] = useState("");
  async function logout() {
    const response = await fetch("/api/access/logout", { method: "POST", headers: { "x-tj-csrf": csrf } });
    if (!response.ok) { setError("Sign-out failed. Reload and try again."); return; }
    window.location.assign("/login");
  }
  return <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground"><span>Read-only assistant access</span><button onClick={logout} className="underline">Sign out</button>{error && <span role="alert">{error}</span>}</div>;
}
