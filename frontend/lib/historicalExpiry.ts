const eastern = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

/** Parse a wall-clock minute in New York, regardless of the browser timezone.
 * Reject invalid dates and DST gaps/folds rather than silently shifting them.
 */
export function historicalExpiryInstant(value: string): string | null {
  const wall = value.trim().replace(" ", "T");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(wall)) return null;
  const nominal = Date.parse(`${wall}:00Z`);
  if (!Number.isFinite(nominal) || new Date(nominal).toISOString().slice(0, 16) !== wall) return null;
  // Sample both sides of a transition to find every possible UTC offset.
  const offsets = new Set<number>();
  for (const hours of [-24, 0, 24]) {
    const sample = nominal + hours * 3_600_000;
    const local = eastern.format(new Date(sample)).replace(" ", "T");
    const offset = Date.parse(`${local}:00Z`) - sample;
    if (!Number.isFinite(offset)) return null;
    offsets.add(offset);
  }
  const matches = [...offsets].map(offset => nominal - offset)
    .filter(at => Number.isFinite(at) && eastern.format(new Date(at)).replace(" ", "T") === wall);
  return matches.length === 1 ? new Date(matches[0]).toISOString() : null;
}
