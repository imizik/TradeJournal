import { redirect } from "next/navigation";
import { mondayOf, newYorkToday } from "@/lib/format";

/** The weekly review opens on the current New York week. */
export default function CurrentWeekPage() {
  redirect(`/daily/week/${mondayOf(newYorkToday())}`);
}
