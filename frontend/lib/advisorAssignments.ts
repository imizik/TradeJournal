import "server-only";
import path from "node:path";
import { accessConfig } from "./accessServer";
import { advisorUnix, ownerSession, socketIdentity } from "./advisorOwner";

let active = 0;
const LIMIT = 8192;
const route = "/owner/advisor/assignments";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

async function boundedBody(request: Request, signal: AbortSignal) {
  if (!request.body) throw new Error("Missing body");
  const reader = request.body.getReader();
  const abort = () => { void reader.cancel(); };
  signal.addEventListener("abort", abort, { once: true });
  try {
    const chunks: Uint8Array[] = []; let size = 0;
    while (true) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.length;
      if (size > LIMIT) throw new Error("Body too large");
      chunks.push(value);
    }
    return Buffer.concat(chunks).toString("utf8");
  } finally { signal.removeEventListener("abort", abort); await reader.cancel(); }
}

export async function advisorAssignments(request: Request) {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const refuse = (status: number, detail: string) => Response.json({ detail }, { status, headers });
  try {
    const config = accessConfig();
    if (config.profile !== "owner") return refuse(403, "Authenticated owner entrance required");
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(5000)]);
    const write = request.method === "POST";
    if (request.method !== "GET" && !write) return refuse(405, "Unsupported method");
    const csrf = write ? request.headers.get("x-tj-csrf") ?? "" : undefined;
    if (write && request.headers.get("origin") !== config.origin) return refuse(403, "Owner origin required");
    const status = await ownerSession(config.target, request.headers, signal, csrf);
    if (status !== 200) return refuse(status, "Owner session unavailable");
    const socket = process.env.TJ_ADVISOR_MANAGER_SOCKET ?? "";
    const uidText = process.env.TJ_ADVISOR_MANAGER_SOCKET_UID ?? "";
    if (process.env.TJ_ADVISOR_MANAGEMENT_ENABLED !== "true") return refuse(503, "Advisor question management is not activated");
    if (!/^\d+$/.test(uidText) || !Number.isSafeInteger(Number(uidText)) || !path.isAbsolute(socket) || path.normalize(socket) !== socket || path.basename(socket) !== "backend.sock") return refuse(503, "Advisor management socket is not configured");
    const url = new URL(request.url); const id = url.searchParams.get("assignment_id");
    if ([...url.searchParams.keys()].some(k => k !== "assignment_id") || url.searchParams.getAll("assignment_id").length > 1 || (id !== null && !uuid.test(id)) || (write && url.search)) return refuse(400, "Use one valid assignment selector for reads only");
    if (!write && (request.headers.get("content-length") && request.headers.get("content-length") !== "0" || request.headers.has("transfer-encoding"))) return refuse(400, "Read accepts no body");
    if (active >= 4) return refuse(429, "Advisor management busy");
    active += 1;
    try {
      let body: string | undefined;
      if (write) {
        if (!request.headers.get("content-type")?.startsWith("application/json")) return refuse(400, "Use bounded JSON");
        body = await boundedBody(request, signal);
        const value = JSON.parse(body);
        const keys = Object.keys(value).sort().join(",");
        if (keys === "revoke") { if (!uuid.test(value.revoke)) return refuse(400, "Invalid revoke assignment"); }
        else if (keys !== "invented_only,operation_id,question,user_plan" || !uuid.test(value.operation_id) || value.invented_only !== true || [value.question, value.user_plan].some(v => typeof v !== "string" || !v.trim() || v.length > 2000)) return refuse(400, "Confirm invented text and supply one question and plan");
      }
      const before = await socketIdentity(socket, Number(uidText));
      const recheck = await ownerSession(config.target, request.headers, signal, csrf);
      if (recheck !== 200) return refuse(recheck, "Owner session unavailable");
      const bytes = await advisorUnix(socket, signal, route + (id ? `?assignment_id=${id}` : ""), body);
      if (before !== await socketIdentity(socket, Number(uidText))) throw new Error("Socket changed");
      const latest = await ownerSession(config.target, request.headers, signal, csrf);
      if (latest !== 200) return refuse(latest, "Owner session unavailable; reload to inspect saved state");
      const value = JSON.parse(bytes.toString("utf8"));
      if (value.schema_version !== "advisor_assignments_v1" || value.demo_only !== true || !Array.isArray(value.assignments)) throw new Error("Unexpected response");
      return new Response(new Uint8Array(bytes), { headers: { ...headers, "Content-Type": "application/json" } });
    } finally { active -= 1; }
  } catch { return refuse(503, "Advisor operation could not be confirmed. Reload saved questions before explicitly retrying; no automatic retry was sent."); }
}
