import "server-only";
import { request as unixRequest } from "node:http";
import { lstat } from "node:fs/promises";
import path from "node:path";
import { accessConfig, upstreamHeaders } from "./accessServer";

const LIMIT = 65536;
const DEADLINE = 5000;
let activeReads = 0;

export async function socketIdentity(socketPath: string, expectedUid: number) {
  let parent = path.dirname(socketPath);
  while (true) {
    const stat = await lstat(parent);
    const stickyRoot = stat.uid === 0 && (stat.mode & 0o1000) !== 0;
    if (!stat.isDirectory() || stat.isSymbolicLink() || ![0, process.getuid?.()].includes(stat.uid) || ((stat.mode & 0o022) !== 0 && !stickyRoot)) throw new Error("Unsafe owner socket parent");
    const next = path.dirname(parent); if (next === parent) break; parent = next;
  }
  const stat = await lstat(socketPath);
  if (!stat.isSocket() || stat.isSymbolicLink() || stat.uid !== expectedUid || (stat.mode & 0o007) !== 0) throw new Error("Unexpected owner socket");
  return `${stat.dev}:${stat.ino}:${stat.uid}:${stat.gid}:${stat.mode}`;
}

export async function ownerSession(target: string, incoming: Headers, signal: AbortSignal, csrf?: string) {
  const response = await fetch(`${target}/access/me`, { headers: upstreamHeaders(incoming), cache: "no-store", redirect: "manual", signal });
  if (response.status === 401) return 401;
  if (!response.ok) return 503;
  const access = await response.json();
  if (csrf !== undefined && (!csrf || csrf !== access.csrf)) return 403;
  return access.enabled === true && access.owner === true ? 200 : 403;
}

export async function advisorUnix(socketPath: string, signal: AbortSignal, route = "/owner/advisor", body?: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const request = unixRequest({ socketPath, path: route, method: body === undefined ? "GET" : "POST", agent: false,
      headers: { Accept: "application/json", "Content-Type": "application/json", "Content-Length": String(Buffer.byteLength(body ?? "")) }, signal }, (response) => {
      if (response.statusCode !== 200 || !response.headers["content-type"]?.startsWith("application/json")) {
        response.destroy(); reject(new Error("Owner reader refused")); return;
      }
      let size = 0; const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > LIMIT) { response.destroy(); reject(new Error("Owner response too large")); }
        else chunks.push(chunk);
      });
      response.on("end", () => resolve(Buffer.concat(chunks)));
      response.on("error", reject);
      response.on("aborted", () => reject(new Error("Owner response incomplete")));
    });
    request.on("error", reject);
    request.end(body);
  });
}

const validReview = (value: { schema_version?: unknown; demo_only?: unknown; request?: unknown }) =>
  value.schema_version === "advisor-owner-review-v1" && value.demo_only === true && !!value.request && "receipt" in value;
const validStatus = (value: { schema_version?: unknown }) => value.schema_version === "advisor-owner-status-v1";
const UNAVAILABLE = "Direct advisor owner review unavailable. Reload to read the saved receipt; no write or retry was sent.";

export const advisorOwner = (request: Request) => ownerRead(request, "/owner/advisor", validReview, UNAVAILABLE);
// States and timestamps only; the owner reader never returns keys, tokens, subjects or config bodies.
export const advisorOwnerStatus = (request: Request) => ownerRead(request, "/owner/advisor/status", validStatus,
  "Advisor connection status unavailable. The owner reader may be stopped; no write or retry was sent.");

// Saved pre-trade checks come from the check service's own owner reader and socket.
const CHECK_ID = /^chk_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CHECK_UNAVAILABLE = "Saved pre-trade checks unavailable. The check owner reader may be stopped; nothing was sent to Jo.";
export const checkOwnerList = (request: Request) => ownerRead(request, "/owner/checks",
  value => value.schema_version === "check-owner-list-v1" && Array.isArray(value.checks), CHECK_UNAVAILABLE, "TJ_CHECK_OWNER");
export const checkOwnerDetail = (request: Request, checkId: string) => CHECK_ID.test(checkId)
  ? ownerRead(request, `/owner/checks/${checkId}`, value => value.schema_version === "check-owner-detail-v1" && value.check_id === checkId,
    CHECK_UNAVAILABLE, "TJ_CHECK_OWNER")
  : Promise.resolve(Response.json({ detail: "Unknown check" }, { status: 404, headers: { "Cache-Control": "no-store" } }));

async function ownerRead(request: Request, route: string, valid: (value: Record<string, unknown>) => boolean, unavailable: string,
  prefix: "TJ_ADVISOR_OWNER" | "TJ_CHECK_OWNER" = "TJ_ADVISOR_OWNER") {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const refusal = (status: number, detail: string) => Response.json({ detail }, { status, headers });
  try {
    const config = accessConfig();
    if (config.profile !== "owner") return refusal(config.profile === "assistant" ? 403 : 503, "Authenticated owner entrance required");
    if (request.method !== "GET" || new URL(request.url).search || request.headers.get("content-length") && request.headers.get("content-length") !== "0" || request.headers.has("transfer-encoding")) return refusal(400, "Use the fixed owner GET without selectors or body");
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(DEADLINE)]);
    const status = await ownerSession(config.target, request.headers, signal);
    if (status !== 200) return refusal(status, "Owner session unavailable");
    const socketPath = process.env[`${prefix}_SOCKET`] ?? "";
    const uidText = process.env[`${prefix}_SOCKET_UID`] ?? "";
    if (process.env[`${prefix}_ENABLED`] !== "true" || !/^\d+$/.test(uidText) || !path.isAbsolute(socketPath) || path.normalize(socketPath) !== socketPath || path.basename(socketPath) !== "owner.sock") return refusal(503, prefix === "TJ_CHECK_OWNER" ? "Pre-trade check review is not switched on yet" : "Direct advisor owner review is not activated");
    const expectedUid = Number(uidText);
    if (!Number.isSafeInteger(expectedUid)) return refusal(503, "Direct advisor owner review is not configured");
    if (activeReads >= 4) return refusal(429, "Owner reader busy");
    activeReads += 1;
    try {
      const before = await socketIdentity(socketPath, expectedUid);
      const body = await advisorUnix(socketPath, signal, route);
      if (before !== await socketIdentity(socketPath, expectedUid)) throw new Error("Owner socket changed");
      // Uncached revalidation closes owner revocation during a slow ledger read.
      const latest = await ownerSession(config.target, request.headers, signal);
      if (latest !== 200) return refusal(latest, "Owner session unavailable");
      const value = JSON.parse(body.toString("utf8"));
      if (!value || typeof value !== "object" || !valid(value)) throw new Error("Invalid owner response");
      return new Response(new Uint8Array(body), { status: 200, headers: { ...headers, "Content-Type": "application/json" } });
    } finally { activeReads -= 1; }
  } catch { return refusal(503, unavailable); }
}
