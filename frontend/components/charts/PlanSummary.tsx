"use client";

import Link from "next/link";
import { audioUrl, captureTime, captureTitle, imageUrl, originLine, TIMING_LABEL } from "@/lib/captures";
import type { Capture } from "@/lib/captures";

/**
 * A linked plan as it was saved (C3.6): its wording, note or recording and
 * transcript, the chart image, and when the server received it against the
 * entry. Corrections and later notes show as added later; nothing here edits it.
 */
export default function PlanSummary({ capture }: { capture: Capture }) {
  const link = capture.link && !capture.link.unresolved ? capture.link : null;
  const transcript = capture.transcript;
  const from = originLine(capture);
  return <article aria-label={`${captureTitle(capture)} plan`} className="space-y-1 text-[11px] text-foreground/80">
    <p><span className="font-medium text-foreground">{captureTitle(capture)}</span> <span className="text-muted-foreground">· received {captureTime(capture.received_at)}</span>
      {link?.timing && <> · <span className={link.timing === "pre_entry" ? "text-emerald-300" : "text-amber-300"}>{TIMING_LABEL[link.timing]}</span></>}
      {link?.method === "manual" && <span className="text-muted-foreground"> · linked by hand</span>}</p>
    {from && <p aria-label="Plan origin"><span className="text-muted-foreground">From: </span>{from.href
      ? <Link href={from.href} className="text-foreground underline">{from.text}</Link> : from.text}</p>}
    {capture.mode === "discretionary" && <p className="text-muted-foreground">Discretionary: no explicit plan was recorded.</p>}
    {capture.wording && <p className="whitespace-pre-wrap"><span className="text-muted-foreground">{capture.setup_label}: </span>{capture.wording}</p>}
    {capture.note && <p className="whitespace-pre-wrap"><span className="text-muted-foreground">Note: </span>{capture.note}</p>}
    {capture.audio && <audio controls preload="none" src={audioUrl(capture.id)} className="h-8 w-full" aria-label="Plan recording" />}
    {transcript && <p className="whitespace-pre-wrap italic text-foreground">{transcript.status === "ready" ? transcript.text || "No speech was recognized." : `Transcript ${transcript.status.replace("_", " ")}.`}
      {transcript.provider && transcript.status === "ready" && <span className="not-italic text-muted-foreground"> ({transcript.provider})</span>}</p>}
    {capture.notes.map((note) => <p key={note.id} className="whitespace-pre-wrap"><span className="text-muted-foreground">{note.kind === "transcript_correction" ? "Transcript corrected" : "Added"} later, {captureTime(note.created_at)}: </span>{note.text}</p>)}
    {capture.image.state === "saved" && <a href={imageUrl(capture.id)} target="_blank" rel="noreferrer" className="text-foreground underline">Chart when saved</a>}
  </article>;
}
