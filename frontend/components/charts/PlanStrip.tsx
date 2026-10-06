"use client";

import { useState } from "react";
import { ChevronDown, Loader2, NotebookPen, RotateCcw, X } from "lucide-react";
import { audioUrl, captureTime, captureTitle, imageUrl, lateBy, SIDE_LABEL } from "@/lib/captures";
import type { Capture, CaptureNote, OutboxItem } from "@/lib/captures";
import { price } from "@/lib/charts";

type Props = {
  capture: Capture | null;
  /** Plans and chart images still in this browser, waiting for Retry. */
  outbox: OutboxItem[];
  narrow: boolean;
  onRetry(item: OutboxItem): void;
  onDismiss(id: string): void;
  onNotTaken(id: string): void;
  onRetryTranscript(id: string): void;
  onNote(id: string, kind: CaptureNote["kind"], text: string): Promise<void>;
};

const TRANSCRIPT_TEXT = { pending: "Recording saved — transcribing", transcribing: "Transcribing…", ready: "Transcript", failed: "Transcription failed", not_configured: "Not transcribed" } as const;

/**
 * The saved plan beside the chart (C3.4): ticker, side, setup and when the
 * server received it, with its full wording, snapshot, recording and transcript
 * one tap away. Saying a plan was not taken keeps it as a record; dismissing
 * only hides the strip on this device.
 */
export default function PlanStrip({ capture, outbox, narrow, onRetry, onDismiss, onNotTaken, onRetryTranscript, onNote }: Props) {
  const [open, setOpen] = useState(false);
  const [writing, setWriting] = useState<CaptureNote["kind"] | null>(null);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");
  const unsent = outbox.filter((item) => item.kind !== "image");
  const images = outbox.filter((item) => item.kind === "image");
  // An image whose plan is not the one shown (dismissed, or a newer plan took the strip) keeps its own Retry here.
  const strayImages = images.filter((item) => item.capture_id !== capture?.id);
  if (!capture && !outbox.length) return null;
  const tap = narrow ? "min-h-11 px-2" : "h-6 px-1.5";
  const transcript = capture?.transcript;
  const late = capture ? lateBy(capture) : null;
  const corrections = capture?.notes.filter((note) => note.kind === "transcript_correction") ?? [];
  const reflections = capture?.notes.filter((note) => note.kind === "note") ?? [];
  const context = capture?.context;

  return <section aria-label="Saved plan" className="min-w-0 shrink-0 border-b border-slate-700/50 bg-[#0f151e] px-2 py-1 text-[11px]">
    {unsent.map((item) => <div key={item.client_id} role="alert" className="flex items-center gap-2 text-amber-200">
      <span className="min-w-0 flex-1 truncate">Not saved: {item.body.underlying} {SIDE_LABEL[item.body.side]}{item.kind === "voice" ? " (voice)" : ""}, written {captureTime(item.created_at / 1000)} on this device. {item.error}</span>
      <button type="button" onClick={() => onRetry(item)} className={`inline-flex shrink-0 items-center gap-1 rounded bg-amber-500/20 text-amber-100 hover:bg-amber-500/30 ${tap}`}><RotateCcw size={11} />Retry</button>
    </div>)}
    {strayImages.map((item) => <div key={item.client_id} role="alert" className="flex items-center gap-2 text-amber-200">
      <span className="min-w-0 flex-1 truncate">Chart image not uploaded: {item.body.underlying} {SIDE_LABEL[item.body.side]} plan, written {captureTime(item.created_at / 1000)}. {item.error}</span>
      <button type="button" onClick={() => onRetry(item)} className={`inline-flex shrink-0 items-center gap-1 rounded bg-amber-500/20 text-amber-100 hover:bg-amber-500/30 ${tap}`}><RotateCcw size={11} />Retry image</button>
    </div>)}
    {capture && <div className={`flex min-w-0 items-center gap-x-2 ${narrow ? "flex-wrap" : ""}`}>
      <NotebookPen size={12} className="shrink-0 text-sky-300" aria-hidden />
      <span className={`font-medium text-slate-100 ${narrow ? "min-w-0 truncate" : "shrink-0"}`}>{captureTitle(capture)}</span>
      <span className={`min-w-0 flex-1 truncate text-slate-400 ${narrow ? "hidden" : ""}`}>{capture.wording ?? capture.note ?? (transcript?.status === "ready" ? transcript.text : "")}</span>
      <span className="shrink-0 text-slate-500" title="When the server received the plan">{captureTime(capture.received_at)}</span>
      <span role="status" className={`shrink-0 ${capture.not_taken_at ? "text-slate-400" : "text-emerald-300"}`}>
        {capture.not_taken_at ? "Not taken" : transcript && transcript.status !== "ready" ? TRANSCRIPT_TEXT[transcript.status] : "Saved"}</span>
      <button type="button" aria-expanded={open} aria-label={open ? "Hide plan details" : "Show plan details"} onClick={() => setOpen((v) => !v)} className={`inline-flex shrink-0 items-center rounded text-slate-400 hover:bg-slate-800 ${tap}`}><ChevronDown size={13} className={open ? "rotate-180" : ""} /></button>
      {!narrow && !capture.not_taken_at && <button type="button" onClick={() => onNotTaken(capture.id)} className={`shrink-0 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 ${tap}`}>Did not take trade</button>}
      <button type="button" aria-label="Dismiss saved plan" title="Hide this strip (the plan stays saved)" onClick={() => { setOpen(false); onDismiss(capture.id); }} className={`inline-flex shrink-0 items-center rounded text-slate-500 hover:bg-slate-800 ${tap}`}><X size={12} /></button>
    </div>}
    {capture && open && <div className="mt-1 space-y-2 border-t border-slate-800 pb-1 pt-2 text-slate-300">
      <p className="text-slate-400">{capture.account_label} · received {captureTime(capture.received_at)}{late ? ` · written ${captureTime(capture.client_captured_at!)} on the device (unverified), sent ${Math.round(late / 60)} min later` : ""}
        {capture.strike != null || capture.expiration || capture.quantity != null ? ` · ${[capture.strike != null ? `${capture.strike} strike` : "", capture.expiration ? `exp ${capture.expiration}` : "", capture.quantity != null ? `qty ${capture.quantity}` : ""].filter(Boolean).join(", ")}` : ""}</p>
      {capture.wording && <p className="whitespace-pre-wrap"><span className="text-slate-500">{capture.setup_label} (template rev {capture.template_revision}): </span>{capture.wording}</p>}
      {capture.mode === "discretionary" && <p className="text-slate-400">Discretionary: no explicit plan.</p>}
      {capture.note && <p className="whitespace-pre-wrap"><span className="text-slate-500">Note: </span>{capture.note}</p>}
      {context?.state === "captured" ? <p className="text-slate-400">Chart then: {context.symbol} {context.interval}, {context.session === "extended" ? "extended hours" : "regular hours"} · {context.price.value != null ? `${price(context.price.value)} (${context.price.source}${context.price.stale ? ", stale" : ""})` : "no price"}
        {` · ${context.levels.length} level${context.levels.length === 1 ? "" : "s"}, ${context.drawings.length} drawing${context.drawings.length === 1 ? "" : "s"}, ${context.auto_levels.length} auto zone${context.auto_levels.length === 1 ? "" : "s"}`}
        {context.basis ? ` · ${context.basis.status === "unknown" ? "splits unknown" : "split-adjusted"}` : ""}</p>
        : <p className="text-amber-300">No chart snapshot: {context?.state === "unavailable" ? context.reason : "not recorded."}</p>}
      {capture.image.state === "saved" ? <a href={imageUrl(capture.id)} target="_blank" rel="noreferrer" className="block w-fit">
          {/* eslint-disable-next-line @next/next/no-img-element -- a private API file, not an optimizable static asset */}
          <img src={imageUrl(capture.id)} alt={`${capture.underlying} chart when the plan was saved`} className="max-h-40 rounded border border-slate-700" /></a>
        : capture.image.state === "pending" ? <p className="text-amber-300">Chart image not uploaded yet.{images.some((item) => item.capture_id === capture.id) ? "" : " The original image is no longer in this browser, so the plan stays without one."}
          {images.filter((item) => item.capture_id === capture.id).map((item) => <button key={item.client_id} type="button" onClick={() => onRetry(item)} className={`ml-2 inline-flex items-center gap-1 rounded bg-amber-500/20 text-amber-100 ${tap}`}><RotateCcw size={11} />Retry image</button>)}</p>
          : null}
      {capture.image.note && capture.image.state === "saved" && <p className="text-[10px] text-slate-500">{capture.image.note}</p>}
      {capture.audio && <div className="space-y-1">
        <audio controls preload="none" src={audioUrl(capture.id)} className="h-8 w-full max-w-md" aria-label="Plan recording" />
        {transcript && <div aria-label="Transcript" className="space-y-1">
          <p className="text-slate-500">{TRANSCRIPT_TEXT[transcript.status]}{transcript.provider && transcript.status === "ready" ? ` · ${transcript.provider}` : ""}
            {(transcript.status === "pending" || transcript.status === "transcribing") && <Loader2 size={11} className="ml-1 inline animate-spin" />}</p>
          {transcript.status === "ready" && <p className="whitespace-pre-wrap italic text-slate-200">{transcript.text || "No speech was recognized."}</p>}
          {(transcript.status === "failed" || transcript.status === "not_configured") && <p className="text-amber-300">{transcript.error}{transcript.status === "failed" ? " The recording is saved." : ""}
            <button type="button" onClick={() => onRetryTranscript(capture.id)} className={`ml-2 inline-flex items-center gap-1 rounded bg-slate-800 text-slate-200 ${tap}`}><RotateCcw size={11} />Retry transcript</button></p>}
          {corrections.map((note) => <p key={note.id} className="whitespace-pre-wrap"><span className="text-slate-500">Corrected later, {captureTime(note.created_at)}: </span>{note.text}</p>)}
        </div>}
      </div>}
      {reflections.map((note) => <p key={note.id} className="whitespace-pre-wrap"><span className="text-slate-500">Added later, {captureTime(note.created_at)}: </span>{note.text}</p>)}
      <div className="flex flex-wrap items-center gap-1.5">
        {narrow && !capture.not_taken_at && <button type="button" onClick={() => onNotTaken(capture.id)} className={`rounded border border-slate-700 text-slate-300 ${tap}`}>Did not take trade</button>}
        {capture.not_taken_at && <span className="text-slate-500">Marked not taken {captureTime(capture.not_taken_at)}.</span>}
        {!writing && capture.mode === "voice" && transcript?.status === "ready" && <button type="button" onClick={() => setWriting("transcript_correction")} className={`rounded border border-slate-700 text-slate-300 ${tap}`}>Correct transcript</button>}
        {!writing && <button type="button" onClick={() => setWriting("note")} className={`rounded border border-slate-700 text-slate-300 ${tap}`}>Add a later note</button>}
      </div>
      {writing && <form className="flex gap-1.5" onSubmit={(event) => { event.preventDefault(); onNote(capture.id, writing, text).then(() => { setWriting(null); setText(""); setProblem(""); }).catch((error: Error) => setProblem(error.message)); }}>
        <input aria-label={writing === "note" ? "Later note" : "Transcript correction"} autoFocus value={text} maxLength={2000} onChange={(event) => setText(event.target.value)}
          placeholder={writing === "note" ? "Shown as added later; the plan itself does not change" : "What was said; the original transcript stays beside it"} className={`min-w-0 flex-1 rounded border border-slate-700 bg-[#10151e] px-2 outline-none ${narrow ? "h-11" : "h-7"}`} />
        <button type="submit" disabled={!text.trim()} className={`rounded bg-slate-700 px-2 text-slate-100 disabled:opacity-40 ${tap}`}>Add</button>
        <button type="button" onClick={() => { setWriting(null); setText(""); }} className={`text-slate-400 ${tap}`}>Cancel</button>
      </form>}
      {problem && <p role="alert" className="text-amber-300">{problem}</p>}
    </div>}
  </section>;
}
