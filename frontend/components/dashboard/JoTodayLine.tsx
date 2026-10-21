"use client";
import { joHeadline, useJoDay } from "@/components/JoDay";

/** One line of Jo's day on the dashboard, linking to the full timeline in today's Daily Review. */
export default function JoTodayLine({ today }: { today: string }) {
  const { data } = useJoDay(today, true);
  const headline = data ? joHeadline(data, today, true) : null;
  return <a href={`/daily/${today}#jo`} data-testid="jo-today-line"
    className="col-span-2 block rounded-md border px-3 py-2 text-sm hover:bg-secondary sm:col-span-4 xl:col-span-2">
    <span className="text-muted-foreground">Jo: </span>
    <span className={headline?.trouble ? "text-amber-200" : "text-foreground"}>{headline ? headline.text : "loading…"}</span>
    <span className="ml-1 text-primary">→</span>
  </a>;
}
