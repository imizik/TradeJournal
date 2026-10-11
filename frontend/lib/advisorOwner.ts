import "server-only";
import { request as unixRequest } from "node:http";
import { lstat } from "node:fs/promises";
import path from "node:path";
import { accessConfig, upstreamHeaders } from "./accessServer";

const LIMIT = 65536;
const DEADLINE = 5000;
let activeReads = 0;

async function socketIdentity(socketPath: string, expectedUid: number) {
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

async function ownerSession(target: string, incoming: Headers, signal: AbortSignal) {
  const response = await fetch(`${target}/access/me`, { headers: upstreamHeaders(incoming), cache: "no-store", redirect: "manual", signal });
  if (response.status === 401) return 401;
  if (!response.ok) return 503;
  const access = await response.json();
  return access.enabled === true && access.owner === true ? 200 : 403;
}

async function singleton(socketPath: string, signal: AbortSignal): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const request = unixRequest({ socketPath, path: "/owner/advisor", method: "GET", agent: false,
      headers: { Accept: "application/json", "Content-Length": "0" }, signal }, (response) => {
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
    request.end();
  });
}

export async function advisorOwner(request: Request) {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const refusal = (status: number, detail: string) => Response.json({ detail }, { status, headers });
  try {
    const config = accessConfig();
    if (config.profile !== "owner") return refusal(config.profile === "assistant" ? 403 : 503, "Authenticated owner entrance required");
    if (request.method !== "GET" || new URL(request.url).search || request.headers.get("content-length") && request.headers.get("content-length") !== "0" || request.headers.has("transfer-encoding")) return refusal(400, "Use the fixed owner GET without selectors or body");
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(DEADLINE)]);
    const status = await ownerSession(config.target, request.headers, signal);
    if (status !== 200) return refusal(status, "Owner session unavailable");
    const socketPath = process.env.TJ_ADVISOR_OWNER_SOCKET ?? "";
    const uidText = process.env.TJ_ADVISOR_OWNER_SOCKET_UID ?? "";
    if (process.env.TJ_ADVISOR_OWNER_ENABLED !== "true" || !/^\d+$/.test(uidText) || !path.isAbsolute(socketPath) || path.normalize(socketPath) !== socketPath || path.basename(socketPath) !== "owner.sock") return refusal(503, "Direct advisor owner review is not activated");
    const expectedUid = Number(uidText);
    if (!Number.isSafeInteger(expectedUid)) return refusal(503, "Direct advisor owner review is not configured");
    if (activeReads >= 4) return refusal(429, "Owner reader busy");
    activeReads += 1;
    try {
      const before = await socketIdentity(socketPath, expectedUid);
      const body = await singleton(socketPath, signal);
      if (before !== await socketIdentity(socketPath, expectedUid)) throw new Error("Owner socket changed");
      // Uncached revalidation closes owner revocation during a slow ledger read.
      const latest = await ownerSession(config.target, request.headers, signal);
      if (latest !== 200) return refusal(latest, "Owner session unavailable");
      const value = JSON.parse(body.toString("utf8"));
      if (value.schema_version !== "advisor-owner-review-v1" || value.demo_only !== true || !value.request || !("receipt" in value)) throw new Error("Invalid owner response");
      return new Response(new Uint8Array(body), { status: 200, headers: { ...headers, "Content-Type": "application/json" } });
    } finally { activeReads -= 1; }
  } catch { return refusal(503, "Direct advisor owner review unavailable. Reload to read the saved receipt; no write or retry was sent."); }
}
