import { accessConfig, currentAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

async function handler(request: Request) {
  try {
    const config = accessConfig();
    if (config.profile === "assistant") return Response.json({ detail: "Not permitted" }, { status: 403 });
    const url = new URL(request.url);
    const host = request.headers.get("host") ?? "";
    const local = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname)
      && ["localhost", "127.0.0.1"].map(name => `${name}${url.port ? `:${url.port}` : ""}`).includes(host);
    // Production remains behind owner-restricted Tailscale Serve, with Next
    // bound to loopback. Host/Origin pinning is CSRF protection, not identity.
    // Never infer a permitted origin from client-supplied forwarded headers.
    const configuredOrigin = process.env.TJ_MOOMOO_WEB_ORIGIN ?? "";
    let privateOrigin = "";
    if (configuredOrigin) {
      const parsed = new URL(configuredOrigin);
      if (parsed.origin !== configuredOrigin || parsed.protocol !== "https:" ||
        !parsed.hostname.endsWith(".ts.net") || parsed.port || parsed.username || parsed.password) {
        return Response.json({ enabled: false }, { status: request.method === "GET" ? 200 : 503 });
      }
      if (host === parsed.host && ["http:", "https:"].includes(url.protocol) &&
        ["localhost", "127.0.0.1", parsed.hostname].includes(url.hostname)) privateOrigin = parsed.origin;
    }
    const permittedOrigin = privateOrigin || (!configuredOrigin && local ? `http://${host}` : "");
    if (config.profile === "owner") {
      const access = await currentAccess();
      if (!access?.enabled || !access.owner) return Response.json({ detail: "Not permitted" }, { status: 403 });
      if (privateOrigin && config.origin !== privateOrigin) return Response.json({ detail: "Not permitted" }, { status: 403 });
    }
    const token = process.env.TJ_MOOMOO_LAB_TOKEN ?? "";
    if (!permittedOrigin || process.env.TJ_MOOMOO_LAB_ENABLED !== "true" || !/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
      return Response.json({ enabled: false }, { status: request.method === "GET" ? 200 : 503 });
    }
    if (url.search || (request.method === "POST" && (request.headers.get("origin") !== permittedOrigin ||
      request.headers.get("content-type") !== "application/x-level2-start"))) {
      return Response.json({ detail: "Fixed same-origin session required" }, { status: 400 });
    }
    if (request.method === "POST" && request.body) {
      const reader = request.body.getReader();
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        if (chunk.value.byteLength) { await reader.cancel(); return Response.json({ detail: "Session takes no arguments" }, { status: 400 }); }
      }
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    request.signal.addEventListener("abort", abort, { once: true });
    if (request.signal.aborted) abort();
    const timeout = setTimeout(abort, 40_000);
    const dispose = () => { clearTimeout(timeout); request.signal.removeEventListener("abort", abort); };
    try {
      const response = await fetch(`http://127.0.0.1:8196/${request.method === "GET" ? "status" : "session"}`, {
        method: request.method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/x-level2-start" },
        redirect: "manual", cache: "no-store", signal: controller.signal,
      });
      if (!response.ok || !response.body || (request.method === "POST" && !response.headers.get("content-type")?.startsWith("application/x-ndjson"))) {
        await response.body?.cancel(); dispose();
        return Response.json({ detail: "Local lab unavailable" }, { status: response.status === 409 ? 409 : 503 });
      }
      const reader = response.body.getReader();
      const stream = new ReadableStream({
        async pull(output) {
          try {
            const chunk = await reader.read();
            if (chunk.done) { dispose(); output.close(); } else output.enqueue(chunk.value);
          } catch { dispose(); output.error(new Error("Local lab stream closed")); }
        },
        async cancel() { abort(); dispose(); await reader.cancel().catch(() => {}); },
      });
      return new Response(stream, { headers: { "Content-Type": request.method === "GET" ? "application/json" : "application/x-ndjson",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Accel-Buffering": "no" } });
    } catch { dispose(); return Response.json({ detail: "Local lab unavailable" }, { status: 503 }); }
  } catch { return Response.json({ detail: "Local lab unavailable" }, { status: 503 }); }
}
export { handler as GET, handler as POST };
