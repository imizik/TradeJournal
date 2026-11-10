import { expect, test } from "@playwright/test";
import { cardLine, historyAnswer, type Proposal } from "../lib/copilot";

// The history sent with the next message carries one line per card with what the owner did with it, so the model knows
// a plan, watch, memory or practice card was confirmed, dismissed or still waits. Not shown on screen.

const PLAN: Proposal = { id: "p1", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "calls", contract: null,
  thesis: "Holds the high", entry_trigger: { condition: "crosses", price: 95.9, interval: "15m" },
  invalidation: { condition: "closes_beyond", price: 92.3, interval: "15m" }, time_stop: null, size_note: null };
const WATCH: Proposal = { id: "w1", kind: "watch", symbol: "CRWV", condition: "touches", price: 88, interval: null, label: "CRWV 88", why: "Gap fill" };
const MEMORY: Proposal = { id: "m1", kind: "memory", memory_kind: "lesson", symbol: null, text: "I chase green [opens]\nand give it back." };
const PRACTICE: Proposal = { id: "r1", kind: "practice", text: "Exit at my invalidation", measure: "exit_at_invalidation",
  label: "exit at my invalidation", target: 0.8, why: "Two rides past the stop" };

test.describe("card lines in the history", () => {
  test("each card says what it proposed and what the owner did", () => {
    expect(cardLine({ ...PLAN, outcome: { state: "confirmed" } })).toBe("[card trade_plan NBIS long calls entry 95.9 stop 92.3: confirmed]");
    expect(cardLine({ ...WATCH, outcome: { state: "dismissed" } })).toBe("[card watch CRWV touches 88: dismissed]");
    expect(cardLine(MEMORY)).toBe('[card memory lesson "I chase green opens and give it back.": waiting]');
    expect(cardLine({ ...PRACTICE, outcome: { state: "confirmed", text: "Out within 15 min of my stop" } }))
      .toBe('[card practice "Out within 15 min of my stop": confirmed]');
    // A plan confirmed with edited levels reports the levels as confirmed.
    const edited: Proposal = { ...PLAN, outcome: { state: "confirmed", fields: { thesis: "x", contract: "", entry: "96.5", invalidation: "93", time_stop: "", size_note: "" } } };
    expect(cardLine(edited)).toBe("[card trade_plan NBIS long calls entry 96.5 stop 93: confirmed]");
  });

  test("the lines follow the answer and the whole stays within the per-message limit", () => {
    expect(historyAnswer("Plan drafted.", undefined, 4000)).toBe("Plan drafted.");
    expect(historyAnswer("Plan drafted.", [PLAN, { ...WATCH, outcome: { state: "dismissed" } }], 4000))
      .toBe("Plan drafted.\n\n[card trade_plan NBIS long calls entry 95.9 stop 92.3: waiting]\n[card watch CRWV touches 88: dismissed]");
    const long = historyAnswer("x".repeat(5000), [PLAN], 4000);
    expect(long.length).toBeLessThanOrEqual(4000);
    expect(long).toContain(" [clipped]\n\n[card trade_plan NBIS");
    expect(historyAnswer("x".repeat(5000), [], 4000)).toBe(`${"x".repeat(3988)} [clipped]`); // as before without cards
  });
});
