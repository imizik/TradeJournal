import { apiUrl } from "./api";

/**
 * Pre-trade captures (C3.4, C3.5): saving the plan before a trade, by template,
 * as discretionary, or by voice. Only the server's acknowledgement makes a plan
 * "Saved". A request that could not reach the server waits in this browser's
 * outbox (IndexedDB, so a recording survives a reload) for an explicit Retry;
 * every retry carries the same `client_id`, so it can never make a second plan.
 */
export type CaptureSide = "buy_calls" | "buy_puts" | "buy_stock" | "short_stock" | "sell_calls" | "sell_puts";
export const FAVORITE_SIDES: CaptureSide[] = ["buy_calls", "buy_puts", "buy_stock"];
export const MORE_SIDES: CaptureSide[] = ["short_stock", "sell_calls", "sell_puts"];
export const SIDE_LABEL: Record<CaptureSide, string> = {
  buy_calls: "Buy calls", buy_puts: "Buy puts", buy_stock: "Buy stock", short_stock: "Short stock", sell_calls: "Sell calls", sell_puts: "Sell puts",
};
export const OPTION_SIDES = new Set<CaptureSide>(["buy_calls", "buy_puts", "sell_calls", "sell_puts"]);
export const CLIP_MS = 30_000;

export type CaptureTemplate = { id: string; setup_label: string; wording: string; revision: number; position: number };
export type CaptureSetup = {
  accounts: { id: string; label: string; broker: string }[]; default_account_id: string | null; templates: CaptureTemplate[]; max_templates: number;
  transcriber: { configured: boolean; provider: string; note: string };
};
export type TranscriptStatus = "pending" | "transcribing" | "ready" | "failed" | "not_configured";
export type CaptureNote = { id: string; kind: "transcript_correction" | "note"; text: string; created_at: number };
export type Capture = {
  id: string; client_id: string; received_at: number; client_captured_at: number | null; account_id: string; account_label: string;
  underlying: string; side: CaptureSide; instrument: "option" | "stock"; mode: "template" | "discretionary" | "voice";
  template_id: string | null; template_revision: number | null; setup_label: string | null; wording: string | null; note: string | null;
  strike: number | null; expiration: string | null; quantity: number | null; context_state: "captured" | "unavailable"; context: CaptureContext;
  image: { state: "pending" | "saved" | "unavailable"; note: string | null; bytes: number | null };
  audio: { type: string; ms: number | null; bytes: number | null } | null;
  transcript: { status: TranscriptStatus; text: string | null; provider: string | null; error: string | null; transcribed_at: number | null } | null;
  not_taken_at: number | null; notes: CaptureNote[];
  /** The trade this plan is linked to (C3.6), resolved now; absent from a backend older than C3.6. */
  link?: CaptureLink | null; link_history?: CaptureLink[];
};
/** pre_entry: received before the entry's minute; unverified: inside it, or no time of day; retrospective: after it. */
export type CaptureTiming = "pre_entry" | "unverified" | "retrospective";
export type LinkCandidate = { trade_id: string; contract: string; entry_time: number; entry_time_reliable: boolean; status: string; timing: CaptureTiming | null };
export type CaptureLink = { id: string; method: "suggested" | "manual"; linked_at: number; unlinked_at: number | null } & (
  (LinkCandidate & { unresolved?: false }) | { unresolved: true; trade_id: null; contract: null; timing: null; note: string });
export type CaptureSummary = {
  since: number; accounts: string[]; eligible: number; confirmed: number; confirmed_discretionary: number; unverified: number;
  retrospective: number; needs_linking: number; no_capture: number; excluded: number;
};
export type CaptureReview = {
  needs_linking: { capture_id: string; suggestions: LinkCandidate[]; others: LinkCandidate[] }[]; unresolved: string[]; count: number;
  summary: CaptureSummary | null; tracking: { since: number | null; accounts: string[] }; captures: Capture[];
};
export const TIMING_LABEL: Record<CaptureTiming, string> = { pre_entry: "Before entry", unverified: "Timing unverified", retrospective: "After entry (retrospective)" };
/**
 * The chart as it stood when the plan was saved, from what the page already
 * held (no market-data request). `unavailable` says why there is none.
 */
export type CaptureContext = { state: "unavailable"; reason: string } | {
  state: "captured"; symbol: string; panel: string; interval: string; session: string; visible_range: { from: number; to: number } | null;
  last_candle: { time: number; close: number } | null;
  price: { value: number | null; source: string; at: number | null; stale: boolean };
  basis: { status: string; splits: { label: string; ex_date: string }[]; as_of: number | null } | null;
  levels: { label: string; price: number }[]; drawings: { kind: string; points: { time: number | null; price: number }[]; text?: string }[];
  auto_levels: { label: string; low: number; high: number }[]; captured_at: number;
};
/** The fields a plan is saved with; `mode` is absent for voice, which the route sets. */
export type CaptureBody = {
  client_id: string; client_captured_at: number; underlying: string; account_id: string; side: CaptureSide; mode?: "template" | "discretionary";
  template_id?: string | null; template_revision?: number | null; note?: string; strike?: number | null; expiration?: string | null; quantity?: number | null;
  context: CaptureContext; image: boolean; image_note?: string; audio_ms?: number;
};

/** The server turned the plan down; sending it again would not help. */
export class CaptureRejected extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { cache: "no-store", ...init });
  } catch {
    throw new Error("The server could not be reached.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof data?.detail === "string" ? data.detail : `The server answered ${response.status}.`;
    // 4xx is about the request itself; a timeout or an overloaded server may answer differently next time.
    throw response.status >= 400 && response.status < 500 && ![408, 429].includes(response.status) ? new CaptureRejected(message) : new Error(message);
  }
  return data as T;
}
const json = (method: string, body?: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const fetchSetup = () => call<CaptureSetup>("/charts/captures/setup");
export const saveDefaultAccount = (id: string | null) => call<CaptureSetup>("/charts/captures/setup", json("PUT", { default_account_id: id }));
export const addTemplate = (setup_label: string, wording: string) => call<CaptureSetup>("/charts/captures/templates", json("POST", { setup_label, wording }));
export const editTemplate = (id: string, setup_label: string, wording: string) => call<CaptureSetup>(`/charts/captures/templates/${id}`, json("PUT", { setup_label, wording }));
export const removeTemplate = (id: string) => call<CaptureSetup>(`/charts/captures/templates/${id}`, { method: "DELETE" });
export const fetchCaptures = () => call<{ captures: Capture[]; needs_linking?: number }>("/charts/captures?limit=20");
export const fetchReview = () => call<CaptureReview>("/charts/captures/review");
export const linkCapture = (id: string, tradeId: string) => call<Capture>(`/charts/captures/${id}/link`, json("POST", { trade_id: tradeId }));
export const unlinkCapture = (id: string) => call<Capture>(`/charts/captures/${id}/unlink`, { method: "POST" });
export const saveTracking = (on: boolean, accounts: string[]) => call<{ since: number | null; accounts: string[] }>("/charts/captures/tracking", json("PUT", { on, accounts }));
export const fetchTradePlans = (tradeId: string) => call<{ captures: Capture[] }>(`/charts/captures/for-trade/${tradeId}`);
export const markNotTaken = (id: string) => call<Capture>(`/charts/captures/${id}/not-taken`, { method: "POST" });
export const addCaptureNote = (id: string, kind: CaptureNote["kind"], text: string) => call<Capture>(`/charts/captures/${id}/notes`, json("POST", { kind, text }));
export const retryTranscript = (id: string) => call<Capture>(`/charts/captures/${id}/transcribe`, { method: "POST" });
export const audioUrl = (id: string) => apiUrl(`/charts/captures/${id}/audio`);
export const imageUrl = (id: string) => apiUrl(`/charts/captures/${id}/image`);

function uploadImage(id: string, image: Blob): Promise<Capture> {
  const form = new FormData();
  form.append("image", image, image.type === "image/png" ? "chart.png" : "chart.jpg");
  return call<Capture>(`/charts/captures/${id}/image`, { method: "POST", body: form });
}

// ---- the outbox: what has not reached the server yet ----

/**
 * One unsent request. `plan` and `voice` are a whole plan (with its frozen
 * chart image, if any); `image` is the frozen image of a plan the server
 * already holds. Nothing else, such as a later screenshot, ever replaces it.
 */
export type OutboxItem = {
  client_id: string; kind: "plan" | "voice" | "image"; body: CaptureBody; audio?: Blob; image?: Blob; capture_id?: string;
  created_at: number; error: string;
};
const DB = "tradejournal-captures";
const STORE = "outbox";
let opened: Promise<IDBDatabase | null> | null = null;
const memory = new Map<string, OutboxItem>();

function database(): Promise<IDBDatabase | null> {
  opened ??= new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "client_id" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch { resolve(null); }
  });
  return opened;
}
function done(request: IDBRequest | IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    if ("oncomplete" in request) { request.oncomplete = () => resolve(); request.onerror = () => reject(request.error); request.onabort = () => reject(request.error); }
    else { request.onsuccess = () => resolve(); request.onerror = () => reject(request.error); }
  });
}
/** Whether an unsent plan survives a reload here: false in a private window or with storage blocked. */
export async function outboxDurable(): Promise<boolean> { return (await database()) !== null; }
export async function outboxPut(item: OutboxItem): Promise<boolean> {
  memory.set(item.client_id, item);
  const db = await database();
  if (!db) return false;
  try { const tx = db.transaction(STORE, "readwrite"); tx.objectStore(STORE).put(item); await done(tx); return true; } catch { return false; }
}
export async function outboxDelete(clientId: string): Promise<void> {
  memory.delete(clientId);
  const db = await database();
  if (!db) return;
  try { const tx = db.transaction(STORE, "readwrite"); tx.objectStore(STORE).delete(clientId); await done(tx); } catch { /* gone with the page */ }
}
export async function outboxAll(): Promise<OutboxItem[]> {
  const db = await database();
  if (!db) return [...memory.values()];
  try {
    const request = db.transaction(STORE, "readonly").objectStore(STORE).getAll();
    await done(request);
    const stored = request.result as OutboxItem[];
    const seen = new Set(stored.map((item) => item.client_id));
    return [...stored, ...[...memory.values()].filter((item) => !seen.has(item.client_id))].sort((a, b) => a.created_at - b.created_at);
  } catch { return [...memory.values()]; }
}

/**
 * Send one outbox item. The item is written to the outbox before the request
 * and removed only when the server has it, so closing the tab mid-send loses
 * nothing. A plan the server turns down leaves the outbox (it would be turned
 * down again) and throws CaptureRejected; anything else stays for Retry.
 * Returns the saved plan, and whether its frozen image is still waiting.
 */
export async function send(item: OutboxItem): Promise<{ capture: Capture; imageWaiting: boolean }> {
  await outboxPut(item);
  let capture: Capture;
  try {
    if (item.kind === "image") {
      capture = await uploadImage(item.capture_id!, item.image!);
      await outboxDelete(item.client_id);
      return { capture, imageWaiting: false };
    }
    if (item.kind === "voice") {
      const form = new FormData();
      form.append("meta", JSON.stringify(item.body));
      form.append("audio", item.audio!, `plan.${(item.audio!.type.split(";")[0].split("/")[1] ?? "webm").replace("mp4", "m4a")}`);
      capture = await call<Capture>("/charts/captures/voice", { method: "POST", body: form });
    } else {
      capture = await call<Capture>("/charts/captures", json("POST", item.body));
    }
  } catch (error) {
    if (error instanceof CaptureRejected) await outboxDelete(item.client_id);
    else await outboxPut({ ...item, error: error instanceof Error ? error.message : "Not sent." });
    throw error;
  }
  await outboxDelete(item.client_id);
  if (!item.image || capture.image.state !== "pending") return { capture, imageWaiting: false };
  const follow: OutboxItem = { client_id: `${item.client_id}-image`, kind: "image", body: item.body, image: item.image, capture_id: capture.id, created_at: item.created_at, error: "" };
  try { return await send(follow); } catch { return { capture, imageWaiting: true }; }
}

// ---- recording ----

/** The recording format this browser can make: Opus in WebM (Chrome, Firefox), else MP4/AAC (Safari). */
export function recordingType(): string | null {
  if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) return null;
  for (const type of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) if (MediaRecorder.isTypeSupported(type)) return type;
  return "";
}

/** A frozen, bounded chart image: at most 1600 px wide, JPEG. */
export function chartImage(canvas: HTMLCanvasElement | null): Promise<Blob | null> {
  if (!canvas || !canvas.width || !canvas.height) return Promise.resolve(null);
  const scale = Math.min(1, 1600 / canvas.width);
  const out = document.createElement("canvas");
  out.width = Math.round(canvas.width * scale);
  out.height = Math.round(canvas.height * scale);
  const context = out.getContext("2d");
  if (!context) return Promise.resolve(null);
  context.fillStyle = "#0b1017";
  context.fillRect(0, 0, out.width, out.height);
  context.drawImage(canvas, 0, 0, out.width, out.height);
  return new Promise((resolve) => { try { out.toBlob((blob) => resolve(blob), "image/jpeg", 0.85); } catch { resolve(null); } });
}

const clock = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" });
const day = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
/** "10:31:05 AM ET", with the date when it is not today. */
export function captureTime(epoch: number, now = Date.now() / 1000): string {
  const when = new Date(epoch * 1000);
  const today = day.format(new Date(now * 1000)) === day.format(when);
  return `${today ? "" : `${day.format(when)} `}${clock.format(when)} ET`;
}
/** A plan's headline: "NVDA · Buy calls · Reclaim". */
export function captureTitle(capture: Pick<Capture, "underlying" | "side" | "mode" | "setup_label">): string {
  const plan = capture.setup_label ?? (capture.mode === "voice" ? "Voice plan" : "Discretionary");
  return `${capture.underlying} · ${SIDE_LABEL[capture.side]} · ${plan}`;
}
/** A plan sent from the outbox long after it was written: the server's time is what counts; the browser's is shown, unverified. */
export function lateBy(capture: Pick<Capture, "received_at" | "client_captured_at">): number | null {
  const late = capture.client_captured_at === null ? 0 : capture.received_at - capture.client_captured_at;
  return late > 60 ? late : null;
}
export const newClientId = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().replaceAll("-", "") : `${Date.now()}${Math.random().toString(36).slice(2)}`);
