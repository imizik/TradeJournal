import { imageUrl, type DrawnPlan } from "./copilot";
import type { CaptureOrigin } from "./captures";

/** Unsent editor state belongs to this owner and browser tab. Only uploaded image IDs survive a reload. */
export type CopilotDraft = {
  text: string;
  images: { id: string; url: string }[];
  typed: boolean;
  spoken: boolean;
  origin: CaptureOrigin;
  drawn: DrawnPlan | null;
  captureChart: boolean;
};

const drafts = new Map<string, CopilotDraft>();

export function draftKey(owner: string, symbol: string, investigation?: string | null, entry = "") {
  return "tradejournal:copilot:draft:" + JSON.stringify([owner, investigation || null, investigation ? "" : symbol.toUpperCase(), entry]);
}

export function readDraft(key: string): CopilotDraft | undefined {
  const cached = drafts.get(key);
  if (cached) return cached;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (typeof saved.text !== "string" || !Array.isArray(saved.images) || !saved.origin) return;
    return { ...saved, images: saved.images.filter((id: unknown) => typeof id === "string" && /^[0-9a-f]{32}$/.test(id))
      .map((id: string) => ({ id, url: imageUrl(id) })) };
  } catch { return; }
}

export function storeDraft(key: string, draft: CopilotDraft | null) {
  if (draft) drafts.set(key, draft); else drafts.delete(key);
  try {
    if (draft) sessionStorage.setItem(key, JSON.stringify({ ...draft, images: draft.images.map(image => image.id) }));
    else sessionStorage.removeItem(key);
  } catch { /* Navigation in this tab still works when browser storage is unavailable. */ }
}

/** The chart usually follows the latest open thread. If its editor was put away mid-draft, return to that exact thread. */
export function chartDraftThread(owner: string, symbol: string): string | null {
  try { return sessionStorage.getItem("tradejournal:copilot:chart-thread:" + JSON.stringify([owner, symbol])); }
  catch { return null; }
}

export function rememberChartDraft(owner: string, symbol: string, thread: string | null) {
  const key = "tradejournal:copilot:chart-thread:" + JSON.stringify([owner, symbol]);
  try { if (thread) sessionStorage.setItem(key, thread); else sessionStorage.removeItem(key); }
  catch { /* Draft text still survives navigation in memory. */ }
}
