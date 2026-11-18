/**
 * Haptic feedback helper for paper order outcomes on the upcoming phone Paper home (not wired in yet).
 *
 * Note: iOS Safari ignores `navigator.vibrate`, so callers must treat this strictly as a best-effort
 * enhancement and never rely on it for user feedback.
 */

export type BuzzKind = "fill" | "reject";

const PATTERNS: Record<BuzzKind, number[]> = {
  fill: [25, 40, 25],
  reject: [80],
};

/** Trigger a short vibration for a paper order fill or reject; returns whether the browser accepted it. */
export function fillBuzz(kind: BuzzKind = "fill"): boolean {
  if (typeof navigator === "undefined" || !("vibrate" in navigator) || typeof navigator.vibrate !== "function") {
    return false;
  }
  try {
    return Boolean(navigator.vibrate(PATTERNS[kind]));
  } catch {
    return false;
  }
}
