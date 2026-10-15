import { accessConfig, currentAccess } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

/** A US stock or ETF ticker (BRK.B style classes included); the bridge checks the same pattern. */
const TICKER = /^[A-Z]{1,5}(\.[A-Z])?$/;

/**
 * Recorded depth for one ticker (heatmap columns, walls, latest profile), read by
 * the loopback bridge from the depth recorder's local files. GET only, with the
 * same owner, origin and enablement rules as the session route; it never reaches
 * the provider. Only the fixed parameters below are forwarded.
 */
export async function GET(request: Request) {
  try {
    const config = accessConfig();
    if (config.profile === "assistant") return Response.json({ detail: "Not permitted" }, { status: 403 });
    const url = new URL(request.url);
    const host = request.headers.get("host") ?? "";
    const local = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname)
      && ["localhost", "127.0.0.1"].map(name => `${name}${url.port ? `:${url.port}` : ""}`).includes(host);
    const configuredOrigin = process.env.TJ_MOOMOO_WEB_ORIGIN ?? "";
    let privateOrigin = "";
    if (configuredOrigin) {
      const parsed = new URL(configuredOrigin);
      if (parsed.origin !== configuredOrigin || parsed.protocol !== "https:" ||
        !parsed.hostname.endsWith(".ts.net") || parsed.port || parsed.username || parsed.password) {
        return Response.json({ detail: "Local lab unavailable" }, { status: 503 });
      }
      if (host === parsed.host && ["http:", "https:"].includes(url.protocol) &&
        ["localhost", "127.0.0.1", parsed.hostname].includes(url.hostname)) privateOrigin = parsed.origin;
    }
    const permitted = !!privateOrigin || (!configuredOrigin && local);
    if (config.profile === "owner") {
      const access = await currentAccess();
      if (!access?.enabled || !access.owner) return Response.json({ detail: "Not permitted" }, { status: 403 });
      if (privateOrigin && config.origin !== privateOrigin) return Response.json({ detail: "Not permitted" }, { status: 403 });
    }
    const token = process.env.TJ_MOOMOO_LAB_TOKEN ?? "";
    if (!permitted || process.env.TJ_MOOMOO_LAB_ENABLED !== "true" || !/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
      return Response.json({ detail: "Local lab unavailable" }, { status: 503 });
    }
    const symbol = url.searchParams.get("symbol") ?? "";
    const kind = url.searchParams.get("kind") ?? "arca";
    const minutes = url.searchParams.get("minutes") ?? "120";
    const bucket = url.searchParams.get("bucket") ?? "10";
    if ([...url.searchParams.keys()].some(name => !["symbol", "kind", "minutes", "bucket"].includes(name))
      || new Set(url.searchParams.keys()).size !== [...url.searchParams.keys()].length
      || !TICKER.test(symbol) || !["arca", "mpid"].includes(kind) || !/^[1-9]\d{0,2}$/.test(minutes) || !["10", "30", "60"].includes(bucket)) {
      return Response.json({ detail: "Invalid depth request" }, { status: 400 });
    }
    const query = new URLSearchParams({ symbol, kind, minutes, bucket });
    const response = await fetch(`http://127.0.0.1:8196/depth?${query}`, {
      headers: { Authorization: `Bearer ${token}` }, redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(15_000),
    });
    if (!response.ok) return Response.json({ detail: "Local lab unavailable" }, { status: response.status === 400 ? 400 : 503 });
    return new Response(response.body, { headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
  } catch { return Response.json({ detail: "Local lab unavailable" }, { status: 503 }); }
}
