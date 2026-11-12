import "server-only";
import { createHash, timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";

/** Owner lock for the private installation (docs/owner-lock.md). Off unless TJ_OWNER_LOCK says otherwise. */
export type LockMode = "off" | "report" | "on";

export function lockMode(): LockMode {
  const value = (process.env.TJ_OWNER_LOCK ?? "off").trim().toLowerCase();
  if (value === "" || value === "off") return "off";
  if (value === "report") return "report";
  return "on"; // "on" and any typo fail closed
}

export const LOCK_COOKIE = "tj_owner_lock";
export const SIGN_IN_PATH = "/sign-in";
/** Set by the gate after it strips every inbound x-tj-* header, so a browser cannot supply it. */
export const CALLER_HEADER = "x-tj-lock-caller";
export const STATE_HEADER = "x-tj-lock-state";

// Inert files a browser or the home-screen installer needs before anyone signs in.
const PUBLIC_FILES = new Set(["/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/manifest.webmanifest", "/deployment.json"]);
const PUBLIC_ROUTES = new Set([SIGN_IN_PATH, "/api/lock/sign-in", "/api/lock/sign-out"]);

function digest(value: string) { return createHash("sha256").update(value).digest(); }

export function localKeyValid(value: string | null) {
  const key = process.env.TJ_OWNER_LOCK_LOCAL_KEY ?? "";
  return key.length >= 32 && !!value && timingSafeEqual(digest(value), digest(key));
}

function hostOf(request: Request) { return (request.headers.get("host") ?? "").toLowerCase(); }

/** Secure cookies everywhere except a plain-http loopback development origin. */
export function secureCookies(request: Request) {
  const host = hostOf(request).replace(/:\d+$/, "");
  return !["localhost", "127.0.0.1", "[::1]"].includes(host);
}

export function cookieName(secure: boolean) { return secure ? `__Host-${LOCK_COOKIE}` : LOCK_COOKIE; }

export function sessionToken(request: { headers: Headers }) {
  const pairs = (request.headers.get("cookie") ?? "").split(";").map(part => part.trim());
  for (const name of [`__Host-${LOCK_COOKIE}`, LOCK_COOKIE]) {
    const pair = pairs.find(part => part.startsWith(`${name}=`));
    const value = pair?.slice(name.length + 1);
    if (value) return value;
  }
  return "";
}

/** State-changing requests must come from a page of this same app (Origin matches the host it was sent to). */
export function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  let host: string;
  try { host = new URL(origin).host.toLowerCase(); } catch { return false; }
  return host === hostOf(request) || host === (request.headers.get("x-forwarded-host") ?? "").toLowerCase();
}

/** Only a path on this app, never another site: "/trades/12?x=1" passes, "//evil", "https://evil" and "/\\evil" do not. */
export function safeNext(value: string | null | undefined) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\") || /[\u0000-\u001f]/.test(value)) return "/";
  if (value === SIGN_IN_PATH || value.startsWith(`${SIGN_IN_PATH}?`) || value.startsWith("/api/")) return "/";
  return value;
}

/** Best-effort network address for the sign-in log only; it never grants anything. */
export function sourceHint(request: Request) {
  const value = (request.headers.get("x-forwarded-for") ?? "").split(",").pop()?.trim() ?? "";
  return /^[0-9A-Fa-f:.]{1,45}$/.test(value) ? value : "unknown";
}

// Positive answers only, for ten seconds, so a page and its requests cost one
// backend check. Ending sessions takes effect at the backend immediately and
// here within those seconds.
const recent = new Map<string, number>();
const REMEMBER_MS = 10_000;

export async function sessionValid(target: string, token: string): Promise<boolean | null> {
  if (!token || token.length > 128) return false;
  const key = digest(token).toString("hex");
  const until = recent.get(key);
  if (until && until > Date.now()) return true;
  try {
    const response = await fetch(`${target}/lock/session`, { headers: { cookie: `${LOCK_COOKIE}=${token}`, "x-tj-lock-browser": "1" }, cache: "no-store", redirect: "manual" });
    if (!response.ok) return null;
    const body = await response.json() as { signed_in?: boolean };
    if (body.signed_in !== true) { recent.delete(key); return false; }
    if (recent.size > 200) recent.clear();
    recent.set(key, Date.now() + REMEMBER_MS);
    return true;
  } catch {
    return null;
  }
}

function pass(headers: Headers) { return NextResponse.next({ request: { headers } }); }

function refuse(status: number, detail: string) {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

/**
 * The private app's front door while the lock is on or reporting. `clean` already
 * has every inbound x-tj-* header removed by proxy.ts.
 */
export async function ownerLockGate(request: NextRequest, clean: Headers, mode: Exclude<LockMode, "off">, target: string) {
  const path = request.nextUrl.pathname;
  if (path.startsWith("/_next/static/") || PUBLIC_FILES.has(path)) return pass(clean);
  if (PUBLIC_ROUTES.has(path)) {
    if (path === SIGN_IN_PATH) clean.set(STATE_HEADER, "sign-in");
    return pass(clean);
  }
  // The deploy health check on the server itself presents the server's local key.
  if (localKeyValid(request.headers.get("x-tj-lock-local"))) {
    clean.set(CALLER_HEADER, "local");
    return pass(clean);
  }
  const would = (reason: string) => console.warn(`owner-lock report-only: would refuse ${request.method} ${path} (${reason})`);
  if (!["GET", "HEAD", "OPTIONS"].includes(request.method) && !sameOrigin(request)) {
    if (mode === "on") return refuse(403, "Request must come from this app");
    would("not from this app");
  }
  const valid = await sessionValid(target, sessionToken(request));
  if (valid === true) return pass(clean);
  if (mode === "report") {
    would(valid === null ? "sign-in check unavailable" : "no owner session");
    // Pages tell an unsigned device to sign in now, before enforcement (the home-screen app has no address bar).
    if (valid === false) clean.set(STATE_HEADER, "unsigned");
    return pass(clean);
  }
  if (valid === null) return refuse(503, "Sign-in check unavailable");
  if (path === "/api/backend/health") return NextResponse.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  if (path.startsWith("/api/")) return refuse(401, "Sign in required");
  // Show the sign-in page in place: the address stays the one asked for (and on
  // the https origin the browser used), and signing in reloads it.
  const signIn = request.nextUrl.clone();
  signIn.pathname = SIGN_IN_PATH;
  signIn.search = "";
  clean.set(STATE_HEADER, "sign-in");
  return NextResponse.rewrite(signIn, { request: { headers: clean }, headers: { "Cache-Control": "no-store" } });
}
