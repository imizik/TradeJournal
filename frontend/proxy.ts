import { NextRequest, NextResponse } from "next/server";
import { accessConfig, upstreamHeaders } from "@/lib/accessServer";

export async function proxy(request: NextRequest) {
  try {
    const config = accessConfig();
    const path = request.nextUrl.pathname;
    const clean = new Headers(request.headers);
    for (const name of [...clean.keys()]) if (name !== "x-tj-csrf" && /^(x-tj-|x-middleware-|x-nextjs-)/i.test(name)) clean.delete(name);
    if (config.profile === "private_legacy") return NextResponse.next({ request: { headers: clean } });
    if (path.startsWith("/_next/static/") || ["/icon-192.png", "/icon-512.png", "/favicon.ico", "/manifest.webmanifest"].includes(path)) return NextResponse.next({ request: { headers: clean } });
    if (config.profile === "assistant" && (path === "/login" || path === "/api/access/challenge" || path === "/api/access/login")) return NextResponse.next({ request: { headers: clean } });
    let cookie: string | null = null;
    let check = await fetch(`${config.target}/access/me`, { headers: upstreamHeaders(clean), cache: "no-store", redirect: "manual" });
    if (check.status === 401 && config.profile === "owner") {
      const response = await fetch(`${config.target}/access/bootstrap`, { method: "POST", headers: { "x-tj-gateway": config.key, "x-tj-bootstrap": "true" }, cache: "no-store", redirect: "manual" });
      if (!response.ok) return NextResponse.json({ detail: "Private access could not be verified" }, { status: 503 });
      cookie = response.headers.get("set-cookie");
      if (!cookie) return NextResponse.json({ detail: "Session could not be established" }, { status: 503 });
      const pair = cookie.split(";", 1)[0];
      const name = pair.split("=", 1)[0];
      const prior = (clean.get("cookie") ?? "").split(";").map(v => v.trim()).filter(v => v && !v.startsWith(`${name}=`));
      clean.set("cookie", [...prior, pair].join("; "));
      check = await fetch(`${config.target}/access/me`, { headers: upstreamHeaders(clean), cache: "no-store", redirect: "manual" });
    }
    if (!check.ok) {
      if (check.status !== 401) return NextResponse.json({ detail: "App access unavailable" }, { status: 503 });
      return path.startsWith("/api/") ? NextResponse.json({ detail: "Authentication required" }, { status: 401 }) : NextResponse.redirect(new URL("/login", config.origin));
    }
    const access = await check.json();
    if (!access.enabled || access.owner !== (config.profile === "owner")) return NextResponse.json({ detail: "Session audience mismatch" }, { status: 403 });
    if (!access.owner && !path.startsWith("/api/") && path !== "/" && path !== "/charts" && !/^\/daily(?:\/[0-9]{4}-[0-9]{2}-[0-9]{2})?$/.test(path) && !(access.grants.journal_read && /^\/(trades|fills|analytics)(\/[^/]+)?$/.test(path))) {
      return NextResponse.json({ detail: "Page is outside your access" }, { status: 403 });
    }
    const response = NextResponse.next({ request: { headers: clean } });
    if (cookie) response.headers.append("set-cookie", cookie);
    response.headers.set("Cache-Control", "no-store");
    response.headers.set("X-Content-Type-Options", "nosniff");
    response.headers.set("Referrer-Policy", "no-referrer");
    response.headers.set("X-Frame-Options", "DENY");
    return response;
  } catch {
    return NextResponse.json({ detail: "App access is not configured" }, { status: 503 });
  }
}

export const config = { matcher: ["/:path*"] };
