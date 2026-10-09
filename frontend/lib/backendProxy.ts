import "server-only";
import { accessConfig, upstreamHeaders } from "./accessServer";

const ROOTS = new Set(["health", "accounts", "fills", "trades", "stats", "rebuild", "quotes", "charts", "daily-review", "market-context", "sync", "webull", "gmail", "packets", "practice", "decisions", "tradingview", "research", "strategy-lab", "auth"]);
const ACCESS = new Set(["challenge", "login", "logout", "me", "assistants", "audit"]);

export async function forward(request: Request, segments: string[], accessRoute = false) {
  try {
    const config = accessConfig();
    if (!segments.length || segments.some((value, index) => {
      const symbolPath = !accessRoute && segments[0] === "charts" && ["symbol", "options"].includes(segments[1]) && index === 2;
      const valid = symbolPath ? /^[A-Za-z0-9_.:-]+(?:\/[A-Za-z0-9_.:-]+)*$/.test(value) : /^[A-Za-z0-9_.:-]+$/.test(value);
      return !valid || value.split("/").some(part => part === "." || part === "..");
    })) return Response.json({ detail: "Invalid path" }, { status: 400 });
    if (!(accessRoute ? ACCESS : ROOTS).has(segments[0])) return Response.json({ detail: "Not found" }, { status: 404 });
    if (accessRoute && segments.length > 1 && !(segments[0] === "assistants" && segments.length === 3 && ["reset", "revoke"].includes(segments[2]))) return Response.json({ detail: "Not found" }, { status: 404 });
    const declared = Number(request.headers.get("content-length") ?? 0);
    if (!Number.isFinite(declared) || declared > 16_000_000) return Response.json({ detail: "Request too large" }, { status: 413 });
    let body: ArrayBuffer | undefined;
    if (!["GET", "HEAD"].includes(request.method) && request.body) {
      const limit = accessRoute ? 16_384 : 16_000_000;
      const chunks: Uint8Array[] = [];
      let size = 0;
      const reader = request.body.getReader();
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > limit) { await reader.cancel(); return Response.json({ detail: "Request too large" }, { status: 413 }); }
        chunks.push(chunk.value);
      }
      const combined = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { combined.set(chunk, offset); offset += chunk.byteLength; }
      body = combined.buffer;
    }
    const source = new URL(request.url);
    const target = `${config.target}/${accessRoute ? "access/" : ""}${segments.map(encodeURIComponent).join("/")}${source.search}`;
    const response = await fetch(target, { method: request.method, headers: upstreamHeaders(request.headers), body,
      redirect: "manual", cache: "no-store", signal: request.signal });
    if (response.status >= 300 && response.status < 400) {
      // Preserve the two existing private-owner Gmail browser redirects only.
      // Never follow a backend redirect server-side or accept a generic target.
      const route = segments.join("/");
      const location = response.headers.get("location");
      if (config.profile !== "assistant" && !accessRoute && location) {
        const destination = new URL(location, config.target);
        if (route === "auth/gmail/callback" && destination.pathname === "/" && [...destination.searchParams.keys()].every(key => key === "gmail_auth") && ["success", "error"].includes(destination.searchParams.get("gmail_auth") ?? "")) {
          return new Response(null, { status: response.status, headers: { Location: `/?gmail_auth=${destination.searchParams.get("gmail_auth")}`, "Cache-Control": "no-store" } });
        }
        if (route === "auth/gmail/start/browser" && destination.origin === "https://accounts.google.com" && ["/o/oauth2/auth", "/o/oauth2/v2/auth"].includes(destination.pathname)) {
          return new Response(null, { status: response.status, headers: { Location: destination.toString(), "Cache-Control": "no-store" } });
        }
      }
      return Response.json({ detail: "Backend redirect was refused" }, { status: 502 });
    }
    // No access key can be reflected in a validation error or server error.
    if (accessRoute && response.status >= 400) return Response.json({ detail: response.status === 429 ? "Try again later" : "Authentication request rejected" }, { status: response.status });
    if (config.profile === "assistant" && response.status >= 500) return Response.json({ detail: "App or market data unavailable" }, { status: response.status });
    const selected = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["content-type", "x-accel-buffering", "retry-after"]) { const value = response.headers.get(name); if (value) selected.set(name, value); }
    if (accessRoute) for (const cookie of response.headers.getSetCookie()) selected.append("set-cookie", cookie);
    return new Response(response.body, { status: response.status, headers: selected });
  } catch {
    return Response.json({ detail: "Backend unavailable" }, { status: 503 });
  }
}
