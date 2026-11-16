/**
 * Every place on the copilot desk, named once (docs/copilot-lab.md § Keys and the palette): its id, its name, its desk key
 * and the palette's hint. The ⌘K palette's place commands are built from this list (``CopilotLab.tsx``, whose
 * ``Record<DeskPlaceId, …>`` of moves will not compile without one per place), and the copilot's ``desk_action`` show
 * takes any id on it (``backend/app/ai/copilot_tools.py`` ``DESK_PLACES``; ``test_copilot_desk_actions.py`` holds the two
 * the same). ``words`` are what a short phrase in ⌘K may say for it ("rules", "nvda chain"), and ``ticker`` says whether
 * a ticker in the phrase goes with it (the place shows that ticker).
 *
 * Moving to a place only moves the desk: an editor opens, nothing is saved, armed, filled or sent.
 */

export type DeskPlaceId = "chart" | "chain" | "ticket" | "check" | "grid" | "feed" | "copilot" | "book" | "threads" | "now"
  | "paper" | "rules" | "goals" | "watchlist" | "note" | "health" | "replay" | "redo" | "day";
export type DeskPlaceEntry = { id: DeskPlaceId; label: string; key?: string; hint: string; words: readonly string[]; ticker?: boolean };

export const DESK_PLACES: readonly DeskPlaceEntry[] = [
  { id: "chart", label: "Chart", key: "C", hint: "The selected ticker's chart", words: ["chart", "charts"], ticker: true },
  { id: "chain", label: "Chain", key: "O", hint: "The selected ticker's option chain", words: ["chain", "options", "option chain"], ticker: true },
  { id: "ticket", label: "Ticket", key: "T", hint: "A plan's ticket to copy. Nothing is sent.", words: ["ticket"] },
  { id: "check", label: "Check a call", key: "L", hint: "Paste a call and check it", words: ["check", "check a call"] },
  { id: "grid", label: "Grid", key: "G", hint: "Your positions and watched names, several charts at once", words: ["grid"] },
  { id: "feed", label: "Feed", key: "F", hint: "Yours, ideas and the market today", words: ["feed"] },
  { id: "copilot", label: "Copilot", key: "/", hint: "The conversation and its message box", words: ["copilot"] },
  { id: "book", label: "Book", key: "B", hint: "Your positions and what needs you", words: ["book", "positions", "my positions"] },
  { id: "threads", label: "Threads", key: "[", hint: "The thread list and previous days", words: ["threads"] },
  { id: "now", label: "Now", hint: "Today's Main chat in the copilot", words: ["now", "main chat"] },
  { id: "paper", label: "Paper book", key: "P", hint: "Paper positions, orders and score. Not real money.", words: ["paper", "paper book"] },
  { id: "rules", label: "My rules", hint: "Write or change your trading rules", words: ["rules", "my rules"] },
  { id: "goals", label: "This week's goals", hint: "Set or change one or two goals for the week", words: ["goals", "my goals"] },
  { id: "watchlist", label: "Watchlist", key: "W", hint: "Your watched names: add, import, plan", words: ["watchlist", "watching"] },
  { id: "note", label: "Note on this position", hint: "A one-line note on the selected position", words: ["note"], ticker: true },
  { id: "health", label: "Data health", hint: "Is every source live: Robinhood, prices, fill emails, Radar", words: ["health", "data health"] },
  { id: "replay", label: "Replay a past day", key: "R", hint: "Practice on a past day's bars. Not live, not real money.", words: ["replay"], ticker: true },
  { id: "redo", label: "Redo one of my trades", hint: "Re-trade a past real trade in replay, then compare", words: ["redo"] },
  { id: "day", label: "Day checklist", key: "D", hint: "The day's checklist. Nothing is sent.", words: ["day", "checklist", "day checklist"] },
];

export const PLACE: ReadonlyMap<DeskPlaceId, DeskPlaceEntry> = new Map(DESK_PLACES.map(p => [p.id, p]));
export const isDeskPlace = (id: unknown): id is DeskPlaceId => typeof id === "string" && PLACE.has(id as DeskPlaceId);

/** A short phrase typed in ⌘K read as a place: "rules", "nvda chain", "chain nvda", "replay aapl". The ticker must be one
 * the desk already knows (``known``, upper case) and go with the place; anything else is null, so the palette's own
 * results stand and nothing is ever sent to the model. A phrase that is a place's words on its own is that place, even
 * when it is also a ticker ("now"). */
export function placeFromWords(text: string, known: ReadonlySet<string>): { place: DeskPlaceEntry; symbol: string | null } | null {
  const words = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length || words.length > 4) return null;
  const named = (phrase: string) => DESK_PLACES.find(p => p.words.includes(phrase)) ?? null;
  const whole = named(words.join(" "));
  if (whole) return { place: whole, symbol: null };
  for (const at of [0, words.length - 1]) {
    const symbol = words[at].toUpperCase();
    if (!known.has(symbol)) continue;
    const place = named(words.filter((_, i) => i !== at).join(" "));
    if (place?.ticker) return { place, symbol };
  }
  return null;
}
