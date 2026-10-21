"use client";

import { useCallback, useRef, useState } from "react";
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
  const knownEntryIds = useRef(new Set(initialJournal?.entries.map((entry) => entry.id) ?? []));
  const markNewContext = useCallback(() => {
    setHasContext(true);
    setContextRevision((revision) => revision + 1);
  }, []);
  const handleEntrySaved = useCallback((entry: { id: string }) => {
    knownEntryIds.current.add(entry.id);
    markNewContext();
  }, [markNewContext]);
  const handleDataLoaded = useCallback((data: DayJournalData) => {
    const hasInputs = data.entries.length > 0 || Object.values(data.trade_plans?.by_trade ?? {}).some((items) => items.length) || !!data.trade_plans?.not_traded?.length;
    if (hasInputs) setHasContext(true);
    const foundNewThought = data.entries.some((entry) => !knownEntryIds.current.has(entry.id));
    for (const entry of data.entries) knownEntryIds.current.add(entry.id);
    if (foundNewThought) setContextRevision((revision) => revision + 1);
  }, []);
  return <>
    {day && canEditJournal && <DayJournal key={day} day={day} review initialData={initialJournal} onEntrySaved={handleEntrySaved} onDataLoaded={handleDataLoaded} />}
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
