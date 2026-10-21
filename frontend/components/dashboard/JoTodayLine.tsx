"use client";
import { joHeadline, useJoDay } from "@/components/JoDay";

/** One line of Jo's day on the dashboard, linking to the full timeline in today's Daily Review. */
export default function JoTodayLine({ today }: { today: string }) {
  const { data } = useJoDay(today, true);
  const headline = data ? joHeadline(data, today, true) : null;
  return <a href={`/daily/${today}#jo`} data-testid="jo-today-line"
    className="block rounded-lg border bg-card px-4 py-3 text-sm hover:bg-secondary">
    <span className="text-muted-foreground">Jo: </span>
    {headline ? headline.parts.map((part, i) => <span key={i}>{i ? " · " : ""}<span className={part.tone === "trouble" ? "text-amber-200" : part.tone === "news" ? "text-sky-300" : "text-foreground"}>{part.text}</span></span>)
      : <span className="text-muted-foreground">loading…</span>}
    <span className="ml-1 text-primary">→</span>
  </a>;
}
