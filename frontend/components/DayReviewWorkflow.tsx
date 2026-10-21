"use client";

import { useState } from "react";
import DayJournal from "@/components/DayJournal";
import DailyAiPanel from "@/components/DailyAiPanel";
import type { DailyReview, DayJournal as DayJournalData } from "@/lib/api";

export default function DayReviewWorkflow({ day, dayLabel, tradeCount, tradeIds, initialReview, initialGeneratedAt, initialJournal, canEditJournal }: {
  day: string | null;
  dayLabel: string;
  tradeCount: number;
  tradeIds: string[];
  initialReview: DailyReview | null;
  initialGeneratedAt: string | null;
  initialJournal: DayJournalData | null;
  canEditJournal: boolean;
}) {
  const [hasContext, setHasContext] = useState(!!initialJournal && (initialJournal.entries.length > 0 || Object.values(initialJournal.trade_plans?.by_trade ?? {}).some((items) => items.length) || !!initialJournal.trade_plans?.not_traded?.length));
  const [contextRevision, setContextRevision] = useState(0);
  return <>
    {day && canEditJournal && <DayJournal key={day} day={day} review initialData={initialJournal} onEntrySaved={() => {
      setHasContext(true);
      setContextRevision((revision) => revision + 1);
    }} />}
    <DailyAiPanel
      tradeCount={tradeCount}
      day={day}
      dayLabel={dayLabel}
      tradeIds={tradeIds}
      initialReview={initialReview}
      initialGeneratedAt={initialGeneratedAt}
      hasDayContext={hasContext}
      contextRevision={contextRevision}
    />
  </>;
}
