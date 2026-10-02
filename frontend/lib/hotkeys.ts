import type { Interval } from "./charts";

/**
 * Chart workspace hotkeys (C0.5). `readHotkey` says what a key press means;
 * the workspace decides when hotkeys are off (a dialog is open, focus is in a
 * text field) and carries the action out. `HOTKEY_HELP` is the cheat sheet,
 * so it must list exactly what `readHotkey` and the workspace handle.
 */

/** Minutes typed as digits, applied on Enter, so typing 15 never passes through 1m. */
export const TYPED_INTERVALS: Readonly<Record<string, Interval>> = { "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m" };
/** Letters that switch the main chart at once, as 4 (4h) does when no digits are waiting. */
const LETTERS: Readonly<Record<string, Interval>> = { h: "1h", d: "1D", w: "1W" };
const MAX_TYPED = 3;

export type Hotkey =
  | { kind: "interval"; interval: Interval }
  /** The digits waiting for Enter after this key; empty closes the entry. */
  | { kind: "type"; typed: string }
  | { kind: "commit" }
  | { kind: "cancel" }
  | { kind: "step"; by: 1 | -1 }
  | { kind: "reset" }
  | { kind: "realtime" }
  | { kind: "help" };

type KeyPress = Pick<KeyboardEvent, "key" | "code" | "altKey" | "ctrlKey" | "metaKey" | "shiftKey">;

/** What a key press means, given the digits typed so far. Browser and OS shortcuts (Ctrl, Cmd) are never taken. */
export function readHotkey(event: KeyPress, typed: string): Hotkey | null {
  const { key, code, altKey, ctrlKey, metaKey, shiftKey } = event;
  if (ctrlKey || metaKey) return null;
  if (altKey) {
    // Option+R types ® on a Mac, so the reset matches the key's position.
    if (code === "KeyR" && !shiftKey) return { kind: "reset" };
    if (key === "ArrowDown" || key === "ArrowUp") return { kind: "step", by: key === "ArrowDown" ? 1 : -1 };
    return null;
  }
  if (typed) {
    if (key === "Enter") return { kind: "commit" };
    if (key === "Escape") return { kind: "cancel" };
    if (key === "Backspace") return { kind: "type", typed: typed.slice(0, -1) };
    if (/^[0-9]$/.test(key)) return { kind: "type", typed: (typed + key).slice(0, MAX_TYPED) };
  } else {
    if (key === "4") return { kind: "interval", interval: "4h" };
    if (/^[0-9]$/.test(key)) return { kind: "type", typed: key };
  }
  if (key === " ") return { kind: "step", by: shiftKey ? -1 : 1 };
  if (key === "?") return { kind: "help" };
  if (key === "End") return { kind: "realtime" };
  const interval = key.length === 1 ? LETTERS[key.toLowerCase()] : undefined;
  return interval ? { kind: "interval", interval } : null;
}

/** The watchlist symbol after (or before) the charted one; a symbol not on the list starts at either end. */
export function stepWatchlist(watchlist: string[], symbol: string, by: 1 | -1): string | null {
  if (!watchlist.length) return null;
  const index = watchlist.indexOf(symbol);
  if (index < 0) return by > 0 ? watchlist[0] : watchlist[watchlist.length - 1];
  return watchlist[(index + by + watchlist.length) % watchlist.length];
}

/** The cheat sheet: words in `keys` are drawn as keys, except the joiners. */
export const HOTKEY_JOINERS = new Set(["then", "or", "+"]);
export const HOTKEY_HELP: { group: string; rows: { keys: string; does: string }[] }[] = [
  { group: "Main chart interval", rows: [
    { keys: "1 3 5 15 30 then Enter", does: "Minutes; nothing changes until Enter" },
    { keys: "Backspace", does: "Erase a typed digit" },
    { keys: "Esc", does: "Cancel a typed interval" },
    { keys: "H", does: "1 hour" },
    { keys: "4", does: "4 hours" },
    { keys: "D", does: "1 day" },
    { keys: "W", does: "1 week" },
  ] },
  { group: "Symbol", rows: [
    { keys: "Space", does: "Next symbol in the watchlist" },
    { keys: "Shift + Space", does: "Previous symbol in the watchlist" },
    { keys: "Alt + ↓ or Alt + ↑", does: "Next or previous symbol in the watchlist" },
    { keys: "⌘ + K or Ctrl + K", does: "Search symbols" },
  ] },
  { group: "View", rows: [
    { keys: "Alt + R", does: "Reset every chart: latest candles, automatic price scale" },
    { keys: "End", does: "Every chart back to the latest candle, same zoom" },
    { keys: "Esc", does: "Leave full screen" },
    { keys: "?", does: "Show or hide this list" },
  ] },
];
