/** Display-only reduction of a frozen packet. Never fetches, fills gaps or infers sessions. */
export type FrozenMinute = { at: number; o: number; h: number; l: number; c: number; v: number; vw: number | null };
export type FrozenQuarter = FrozenMinute & { count: number; complete: boolean };
export type FrozenWindow = { minutes: FrozenMinute[]; quarters: FrozenQuarter[]; cutoff: number };
const minute = 60_000;
const quarter = 15 * minute;
export function frozenWindow(raw: unknown, cutoffText: string): FrozenWindow {
  const cutoff = /(?:Z|[+-]\d{2}:\d{2})$/.test(cutoffText) ? Date.parse(cutoffText) : NaN;
  if (!Number.isFinite(cutoff) || !Array.isArray(raw) || raw.length === 0 || raw.length > 240) throw new Error("Missing or unsupported frozen minute window.");
  const seen = new Set<number>();
  const minutes = raw.map((value: unknown): FrozenMinute => {
    if (!value || typeof value !== "object") throw new Error("Invalid frozen bar.");
    const bar = value as Record<string, unknown>;
    const at = typeof bar.t === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(bar.t) ? Date.parse(bar.t) : NaN;
    if (!Number.isFinite(at) || at % minute !== 0 || at + minute > cutoff || seen.has(at)) throw new Error("Duplicate, unaligned or unfinished frozen minute.");
    seen.add(at);
    const values = [bar.o, bar.h, bar.l, bar.c];
    if (!values.every(n => typeof n === "number" && Number.isFinite(n) && n > 0 && n <= Number.MAX_SAFE_INTEGER) || typeof bar.v !== "number" || !Number.isSafeInteger(bar.v) || bar.v < 0) throw new Error("Invalid frozen price or volume.");
    const [o, h, l, c] = values as number[];
    if (l > Math.min(o, c) || h < Math.max(o, c)) throw new Error("Invalid frozen OHLC range.");
    const vw = typeof bar.vw === "number" && Number.isFinite(bar.vw) && bar.vw > 0 && bar.vw <= Number.MAX_SAFE_INTEGER ? bar.vw : null;
    return { at, o, h, l, c, v: bar.v, vw };
  }).sort((a, b) => a.at - b.at);
  const groups = new Map<number, FrozenMinute[]>();
  for (const bar of minutes) {
    const at = Math.floor(bar.at / quarter) * quarter;
    groups.set(at, [...(groups.get(at) ?? []), bar]);
  }
  const quarters = [...groups].map(([at, bars]): FrozenQuarter => ({ at, o: bars[0].o,
    h: Math.max(...bars.map(b => b.h)), l: Math.min(...bars.map(b => b.l)), c: bars.at(-1)!.c,
    v: bars.reduce((sum, b) => sum + b.v, 0), vw: bars.at(-1)!.vw, count: bars.length,
    complete: bars.length === 15 && bars.every((bar, i) => bar.at === at + i * minute) && at + quarter <= cutoff }));
  if (quarters.some(bar => !Number.isSafeInteger(bar.v))) throw new Error("Frozen volume total exceeds supported precision.");
  return { minutes, quarters, cutoff };
}
