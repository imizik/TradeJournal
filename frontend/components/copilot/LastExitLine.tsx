import type { ExitLesson } from "@/lib/copilot";

const SAID: Record<string, string> = { yes: "followed", partly: "partly followed", no: "didn't follow" };
const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

/** One quiet line of the symbol's newest answered exit review, under a new plan (the plan card, Arm today's plans):
 * "Last NBIS exit (Oct 21): didn't follow · “No, sold the give-back too early.”" The owner's own words; nothing without one. */
export default function LastExitLine({ symbol, lesson }: { symbol: string; lesson: ExitLesson | null | undefined }) {
  if (!lesson) return null;
  return (
    <p aria-label={`Last ${symbol} exit lesson`} title={lesson.lesson} className="line-clamp-2 text-xs text-muted-foreground">
      <span className="text-foreground">Last {symbol} exit ({day(lesson.exited)}):</span>
      {lesson.followed && ` ${SAID[lesson.followed]} ·`} “{lesson.lesson}”
    </p>
  );
}
