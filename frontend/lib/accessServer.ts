import "server-only";
import { cache } from "react";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { PRIVATE_ACCESS, type AppAccess } from "./accessTypes";

export function accessConfig() {
  const profile = process.env.TJ_ACCESS_PROFILE ?? "private_legacy";
  if (!["private_legacy", "owner", "assistant"].includes(profile)) throw new Error("Invalid access profile");
  const target = new URL(process.env.API_INTERNAL_URL ?? process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8080");
  if (target.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(target.hostname) || target.username || target.password || target.pathname !== "/" || target.search || target.hash) throw new Error("API upstream must be a loopback HTTP origin");
  const key = process.env.TJ_GATEWAY_KEY ?? "";
  const origin = process.env.TJ_WEB_ORIGIN ?? "";
  if (profile !== "private_legacy") {
    if (process.env.NEXT_PUBLIC_API_URL !== "/api/backend") throw new Error("Authenticated builds require the same-origin API path");
    if (profile === "assistant" && process.env.TJ_ASSISTANT_ENABLED !== "true") throw new Error("Assistant entrance is disabled");
    const parsed = new URL(origin);
    if (key.length < 32 || parsed.origin !== origin || (parsed.protocol !== "https:" && !(process.env.TJ_ACCESS_ALLOW_LOCAL_HTTP === "true" && parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname)))) throw new Error("App access is not configured");
  }
  return { profile, target: target.origin, key, origin };
}

export function upstreamHeaders(incoming: Headers) {
  const config = accessConfig();
  const selected = new Headers();
  for (const name of ["cookie", "content-type", "origin", "x-tj-csrf", "accept", "last-event-id"]) {
    const value = incoming.get(name); if (value) selected.set(name, value);
  }
  if (config.profile !== "private_legacy") selected.set("x-tj-gateway", config.key);
  return selected;
}

export const currentAccess = cache(async (): Promise<AppAccess | null> => {
  const config = accessConfig();
  if (config.profile === "private_legacy") return PRIVATE_ACCESS;
  const response = await fetch(`${config.target}/access/me`, { headers: upstreamHeaders(new Headers(await headers())), cache: "no-store", redirect: "manual" });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("App access could not be verified");
  const value = await response.json() as AppAccess;
  if (!value.enabled || value.owner !== (config.profile === "owner")) throw new Error("Invalid app session audience");
  return value;
});

export async function requireAccess() {
  const value = await currentAccess();
  if (!value) redirect("/login");
  return value;
}
