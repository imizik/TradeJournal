"use client";

import { audioUrl, captureTime, captureTitle, imageUrl, TIMING_LABEL } from "@/lib/captures";
import type { Capture } from "@/lib/captures";

/**
 * A linked plan as it was saved (C3.6): its wording, note or recording and
 * transcript, the chart image, and when the server received it against the
 * entry. Corrections and later notes show as added later; nothing here edits it.
 */
export default function PlanSummary({ capture }: { capture: Capture }) {
  const link = capture.link && !capture.link.unresolved ? capture.link : null;
  const transcript = capture.transcript;
  return <article aria-label={`${captureTitle(capture)} plan`} className="space-y-1 text-[11px] text-slate-300">
    <p><span className="font-medium text-slate-100">{captureTitle(capture)}</span> <span className="text-slate-500">· received {captureTime(capture.received_at)}</span>
      {link?.timing && <> · <span className={link.timing === "pre_entry" ? "text-emerald-300" : "text-amber-300"}>{TIMING_LABEL[link.timing]}</span></>}
      {link?.method === "manual" && <span className="text-slate-500"> · linked by hand</span>}</p>
    {capture.mode === "discretionary" && <p className="text-slate-400">Discretionary: no explicit plan was recorded.</p>}
    {capture.wording && <p className="whitespace-pre-wrap"><span className="text-slate-500">{capture.setup_label}: </span>{capture.wording}</p>}
    {capture.note && <p className="whitespace-pre-wrap"><span className="text-slate-500">Note: </span>{capture.note}</p>}
    {capture.audio && <audio controls preload="none" src={audioUrl(capture.id)} className="h-8 w-full" aria-label="Plan recording" />}
    {transcript && <p className="whitespace-pre-wrap italic text-slate-200">{transcript.status === "ready" ? transcript.text || "No speech was recognized." : `Transcript ${transcript.status.replace("_", " ")}.`}
      {transcript.provider && transcript.status === "ready" && <span className="not-italic text-slate-500"> ({transcript.provider})</span>}</p>}
    {capture.notes.map((note) => <p key={note.id} className="whitespace-pre-wrap"><span className="text-slate-500">{note.kind === "transcript_correction" ? "Transcript corrected" : "Added"} later, {captureTime(note.created_at)}: </span>{note.text}</p>)}
    {capture.image.state === "saved" && <a href={imageUrl(capture.id)} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">Chart when saved</a>}
  </article>;
}
