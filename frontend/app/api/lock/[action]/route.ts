import { accessConfig } from "@/lib/accessServer";
import { cookieName, lockMode, sameOrigin, secureCookies, sessionToken, sourceHint, LOCK_COOKIE } from "@/lib/ownerLock";

export const dynamic = "force-dynamic";

const ACTIONS = new Set(["sign-in", "sign-out", "sign-out-everywhere"]);
const NO_STORE = { "Cache-Control": "no-store" };

function cleared(response: Response) {
  // Clear both names: the __Host- one on https and the plain one on a loopback dev origin.
  response.headers.append("set-cookie", `__Host-${LOCK_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`);
  response.headers.append("set-cookie", `${LOCK_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax`);
  return response;
}

export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (lockMode() === "off" || !ACTIONS.has(action)) return Response.json({ detail: "Not Found" }, { status: 404, headers: NO_STORE });
  if (!sameOrigin(request)) return Response.json({ detail: "Request must come from this app" }, { status: 403, headers: NO_STORE });
  const { target } = accessConfig();
  const token = sessionToken(request);
  const upstream = { "x-tj-lock-browser": "1", ...(token ? { cookie: `${LOCK_COOKIE}=${token}` } : {}) };
  try {
    if (action === "sign-in") {
      const raw = await request.text();
      if (raw.length > 4096) return Response.json({ detail: "Request too large" }, { status: 413, headers: NO_STORE });
      let passphrase: unknown;
      try { passphrase = (JSON.parse(raw) as { passphrase?: unknown }).passphrase; } catch { passphrase = undefined; }
      if (typeof passphrase !== "string" || !passphrase || passphrase.length > 256) return Response.json({ detail: "Sign-in failed" }, { status: 401, headers: NO_STORE });
      const response = await fetch(`${target}/lock/sign-in`, { method: "POST", cache: "no-store", redirect: "manual",
        headers: { "x-tj-lock-browser": "1", "x-tj-lock-source": sourceHint(request), "content-type": "application/json" },
        body: JSON.stringify({ passphrase }) });
      if (!response.ok) {
        const detail = response.status === 429 ? "Too many attempts. Wait 15 minutes and try again."
          : response.status === 503 ? "Sign-in is not set up on this server yet." : "That passphrase did not work.";
        return Response.json({ detail }, { status: response.status === 429 || response.status === 503 ? response.status : 401, headers: NO_STORE });
      }
      const body = await response.json() as { token: string; max_age: number };
      const secure = secureCookies(request);
      const result = Response.json({ signed_in: true }, { headers: NO_STORE });
      result.headers.append("set-cookie", `${cookieName(secure)}=${body.token}; Path=/; Max-Age=${body.max_age}; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`);
      return result;
    }
    const response = await fetch(`${target}/lock/${action}`, { method: "POST", headers: upstream, cache: "no-store", redirect: "manual" });
    if (!response.ok) return Response.json({ detail: response.status === 401 ? "Sign in required" : "Sign-out failed" }, { status: response.status, headers: NO_STORE });
    return cleared(Response.json(await response.json(), { headers: NO_STORE }));
  } catch {
    return Response.json({ detail: "Backend unavailable" }, { status: 503, headers: NO_STORE });
  }
}
