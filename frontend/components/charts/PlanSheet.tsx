"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Loader2, Mic, Pencil, Plus, Settings2, Square, Trash2, X } from "lucide-react";
import { addTemplate, CaptureRejected, chartImage, CLIP_MS, editTemplate, FAVORITE_SIDES, MORE_SIDES, newClientId, OPTION_SIDES, outboxDurable, recordingType, removeTemplate, saveDefaultAccount, send, SIDE_LABEL } from "@/lib/captures";
import type { Capture, CaptureBody, CaptureContext, CaptureSetup, CaptureSide, OutboxItem } from "@/lib/captures";

/** What the chart can give a plan at the moment it is saved: its state and its picture. */
export type ChartSnapshot = { context: CaptureContext; canvas: HTMLCanvasElement | null; imageNote: string };

type Props = {
  /** The symbol when the sheet opened: frozen, whatever the chart shows next. */
  symbol: string;
  /** What the main chart shows now, to say so when it has moved on. */
  chartSymbol: string;
  setup: CaptureSetup | null;
  setupError: string;
  narrow: boolean;
  snapshot(symbol: string): ChartSnapshot;
  onSetup(setup: CaptureSetup): void;
  onSaved(capture: Capture, imageWaiting: boolean): void;
  /** A plan that could not reach the server, now waiting in this browser's outbox. */
  onQueued(): void;
  onClose(): void;
};

type Phase = "idle" | "asking" | "recording" | "review" | "denied" | "failed";
type Recording = { blob: Blob; ms: number; url: string };
const HOLD_MS = 400;
const secs = (ms: number) => `0:${String(Math.min(30, Math.floor(ms / 1000))).padStart(2, "0")}`;

/**
 * The microphone (C3.5). Press and hold records until release, which saves; a
 * short press, the keyboard, or a permission prompt that ate the hold switches
 * to tap mode with Stop & save. The 30-second limit, a cancelled pointer, a
 * hidden tab or a lost device stop the clip and offer Save or Discard. The
 * microphone is asked for only when the user starts recording.
 */
function useRecorder(onFinished: (recording: Recording) => void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [mode, setMode] = useState<"hold" | "tap">("hold");
  const [elapsed, setElapsed] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [reason, setReason] = useState("");
  const state = useRef({ phase: "idle" as Phase, mode: "hold" as "hold" | "tap", released: false, save: false, discard: false, started: 0 });
  const media = useRef<{ recorder: MediaRecorder; stream: MediaStream; timer: number } | null>(null);
  const finished = useRef(onFinished);
  useEffect(() => { finished.current = onFinished; });
  const go = (next: Phase) => { state.current.phase = next; setPhase(next); };
  const switchMode = (next: "hold" | "tap") => { state.current.mode = next; setMode(next); };

  const stop = (save: boolean, why = "") => {
    const current = media.current;
    if (!current) return;
    state.current.save = save;
    if (why) setReason(why);
    window.clearInterval(current.timer);
    if (current.recorder.state !== "inactive") current.recorder.stop();
  };
  const start = async (how: "hold" | "tap") => {
    if (state.current.phase === "asking" || state.current.phase === "recording") return;
    const type = recordingType();
    if (type === null) { setReason("This browser cannot record audio here. Save with a template or Discretionary."); go("failed"); return; }
    state.current.released = false; state.current.discard = false; switchMode(how); setReason(""); setElapsed(0);
    go("asking");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      const denied = error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
      setReason(denied ? "Microphone access is blocked. Allow it for this site in the browser’s settings, or save with a template or Discretionary."
        : "No microphone could be opened. Save with a template or Discretionary.");
      go(denied ? "denied" : "failed");
      return;
    }
    if (state.current.discard) { stream.getTracks().forEach((track) => track.stop()); go("idle"); return; }
    // The permission prompt took the press: keep recording, and let Stop & save end it.
    if (how === "hold" && state.current.released) switchMode("tap");
    const recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      media.current = null;
      const ms = Math.min(CLIP_MS, Math.round(performance.now() - state.current.started));
      if (state.current.discard || !chunks.length) {
        if (!state.current.discard) setReason("Recording stopped before any sound was captured. Nothing was recorded.");
        setRecording(null); go("idle"); return;
      }
      const blob = new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" });
      const made = { blob, ms, url: URL.createObjectURL(blob) };
      setRecording(made); go("review");
      if (state.current.save) finished.current(made);
    };
    stream.getTracks().forEach((track) => { track.onended = () => stop(false, "The microphone stopped (another app or device took it). Save what was recorded, or discard it."); });
    state.current.started = performance.now();
    const timer = window.setInterval(() => {
      const ms = performance.now() - state.current.started;
      setElapsed(ms);
      if (ms >= CLIP_MS) stop(false, "That is the 30-second limit. Save the clip or discard it.");
    }, 100);
    media.current = { recorder, stream, timer };
    recorder.start(250);
    go("recording");
  };
  /** The press ended: a hold saves; a short press keeps recording in tap mode. */
  const release = () => {
    if (state.current.mode !== "hold") return;
    if (state.current.phase === "asking") { state.current.released = true; return; }
    if (state.current.phase !== "recording") return;
    if (performance.now() - state.current.started < HOLD_MS) switchMode("tap");
    else stop(true);
  };
  const interrupt = (why: string) => {
    if (state.current.phase === "recording") stop(false, why);
    // Still waiting for the microphone: it is put down unused when it arrives.
    else if (state.current.phase === "asking") { state.current.discard = true; setReason(why.replace("Save what was recorded, or discard it.", "Nothing was recorded.")); }
  };
  const latest = useRef({ interrupt });
  useEffect(() => { latest.current = { interrupt }; });
  const discard = () => {
    state.current.discard = true;
    if (media.current) stop(false);
    if (recording) URL.revokeObjectURL(recording.url);
    setRecording(null); setReason(""); go("idle");
  };
  useEffect(() => {
    const flags = state.current;
    const holder = media;
    const hidden = () => { if (document.hidden) latest.current.interrupt("Recording stopped when the page was hidden. Save what was recorded, or discard it."); };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      // Closing the sheet mid-clip discards it; nothing is ever uploaded unasked.
      flags.discard = true;
      const current = holder.current;
      if (current) { window.clearInterval(current.timer); if (current.recorder.state !== "inactive") current.recorder.stop(); current.stream.getTracks().forEach((track) => track.stop()); }
    };
  }, []);
  return { phase, mode, elapsed, recording, reason, start, release, interrupt, stop, discard };
}

/**
 * Plan trade (C3.4, C3.5): ticker and account frozen at open, an explicit side,
 * a template (or Discretionary), Save. Or a voice note in place of the
 * template. Nothing here recommends a trade or sends an order.
 */
export default function PlanSheet({ symbol: opened, chartSymbol, setup, setupError, narrow, snapshot, onSetup, onSaved, onQueued, onClose }: Props) {
  const [symbol, setSymbol] = useState(opened);
  const [editingSymbol, setEditingSymbol] = useState(false);
  const accounts = setup?.accounts ?? [];
  // The default account (or the only one) until the user picks another; setup that loads late still fills it in.
  const fallback = setup?.default_account_id ?? (accounts.length === 1 ? accounts[0].id : "");
  const [picked, setAccount] = useState<string | null>(null);
  const account = picked ?? fallback;
  const [side, setSide] = useState<CaptureSide | null>(null);
  const [more, setMore] = useState(false);
  const [template, setTemplate] = useState<string | null>(null);
  const [discretionary, setDiscretionary] = useState(false);
  const [note, setNote] = useState("");
  const [details, setDetails] = useState(false);
  const [strike, setStrike] = useState("");
  const [expiration, setExpiration] = useState("");
  const [quantity, setQuantity] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // A plan that did not reach the server: its exact request waits for Retry, and the form is locked so it cannot drift from it.
  const [stuck, setStuck] = useState<OutboxItem | null>(null);
  const [editing, setEditing] = useState(false);
  const clientId = useRef(newClientId());
  const dialog = useRef<HTMLDivElement>(null);
  const templates = setup?.templates ?? [];
  const chosen = templates.find((row) => row.id === template) ?? null;
  const recorder = useRecorder((recording) => void submit(recording));
  const busy = saving || recorder.phase === "asking" || recorder.phase === "recording";
  const canSave = !!account && !!side && (!!chosen || discretionary) && !busy && !stuck;
  useEffect(() => { dialog.current?.focus({ preventScroll: true }); }, []);

  async function submit(voice?: { blob: Blob; ms: number }) {
    if (saving || stuck) return;
    if (!account) { setError("Choose the journal account first."); return; }
    if (!side) { setError("Choose what you are taking first."); return; }
    if (!voice && !chosen && !discretionary) { setError("Choose a template, or Discretionary."); return; }
    setSaving(true); setError("");
    // Frozen now: the chart as it stands at this moment, never a later one.
    let shot: ChartSnapshot;
    try { shot = snapshot(symbol); } catch { shot = { context: { state: "unavailable", reason: "The chart could not be read." }, canvas: null, imageNote: "" }; }
    const image = shot.context.state === "captured" ? await chartImage(shot.canvas).catch(() => null) : null;
    const option = OPTION_SIDES.has(side);
    const body: CaptureBody = {
      client_id: clientId.current, client_captured_at: Date.now(), underlying: symbol, account_id: account, side,
      ...(voice ? {} : { mode: chosen ? "template" as const : "discretionary" as const }),
      template_id: chosen?.id ?? null, template_revision: chosen?.revision ?? null, note: note.trim() || undefined,
      strike: option && strike ? Number(strike) : null, expiration: option && expiration ? expiration : null, quantity: quantity ? Number(quantity) : null,
      context: shot.context, image: !!image,
      image_note: image ? shot.imageNote : shot.context.state === "captured" ? "The chart image could not be made." : undefined,
      audio_ms: voice?.ms,
    };
    const item: OutboxItem = { client_id: clientId.current, kind: voice ? "voice" : "plan", body, audio: voice?.blob, image: image ?? undefined, created_at: Date.now(), error: "" };
    await deliver(item);
  }
  async function deliver(item: OutboxItem) {
    setSaving(true); setError("");
    try {
      const { capture, imageWaiting } = await send(item);
      onSaved(capture, imageWaiting);
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : "Not saved.";
      if (failure instanceof CaptureRejected) { setError(`Not saved: ${message}`); setStuck(null); }
      else {
        const kept = await outboxDurable();
        setStuck(item);
        setError(`Not saved yet: ${message} ${kept ? "It is kept in this browser; Retry sends it, here or from the strip beside the chart." : "This browser cannot keep it after the tab closes; keep this tab open and Retry."}`);
        onQueued();
      }
    } finally { setSaving(false); }
  }

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape" && !busy) { event.preventDefault(); onClose(); return; }
    if (event.key !== "Enter" || event.repeat || event.nativeEvent.isComposing) return;
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select, [data-own-enter]")) return;
    event.preventDefault();
    if (canSave) void submit();
  };
  const sideButton = (value: CaptureSide) => <button key={value} type="button" aria-pressed={side === value} onClick={() => { setSide(value); setError(""); }}
    className={`rounded-md border px-2.5 text-xs ${narrow ? "min-h-11" : "min-h-8"} ${side === value ? "border-sky-400 bg-sky-400/15 text-sky-100" : "border-slate-700 text-slate-300 hover:bg-slate-800"}`}>{SIDE_LABEL[value]}</button>;
  const accountLabel = accounts.find((row) => row.id === account)?.label;
  const transcriber = setup?.transcriber;

  const panel = <div ref={dialog} role="dialog" aria-modal="true" aria-label="Plan trade" tabIndex={-1} onKeyDown={onKey}
    className={`${narrow ? "max-h-[88vh] w-full rounded-t-xl border-t pb-[max(0.75rem,env(safe-area-inset-bottom))]" : "max-h-[calc(100vh-6rem)] w-[380px] rounded-xl border"} overflow-y-auto overscroll-contain border-slate-600 bg-[#121924] text-slate-300 shadow-2xl outline-none`}>
    {narrow && <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-slate-600" aria-hidden />}
    <div className="flex items-center gap-2 border-b border-slate-700/60 px-3 py-2">
      <h2 className="text-xs font-medium text-slate-200">Plan trade</h2>
      <span className="text-[10px] text-slate-500">Main chart</span>
      <div className="ml-auto flex items-center gap-1">
        <button type="button" aria-label="Capture setup" aria-pressed={editing} title="Default account and favorite templates" onClick={() => setEditing((v) => !v)}
          className={`inline-flex items-center justify-center rounded-md ${narrow ? "h-11 w-11" : "h-7 w-7"} ${editing ? "bg-sky-400/15 text-sky-300" : "text-slate-400 hover:bg-slate-800"}`}><Settings2 size={14} /></button>
        <button type="button" aria-label="Close plan" disabled={busy} onClick={onClose} className={`inline-flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 disabled:opacity-40 ${narrow ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
      </div>
    </div>

    {/* What this plan is for, frozen when the sheet opened; only an explicit change moves it. */}
    <div className="space-y-1.5 px-3 pt-2.5" aria-label="Plan for">
      <div className="flex items-center gap-2">
        {editingSymbol ? <input aria-label="Plan symbol" autoFocus value={symbol} maxLength={15} disabled={!!stuck}
          onChange={(event) => setSymbol(event.target.value.toUpperCase().replace(/[^A-Z0-9./-]/g, ""))} onBlur={() => { if (!symbol) setSymbol(opened); setEditingSymbol(false); }}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); setEditingSymbol(false); } }}
          className="h-8 w-24 rounded border border-slate-600 bg-[#10151e] px-2 text-base font-semibold uppercase text-white outline-none focus:border-sky-500" />
          : <span data-testid="plan-symbol" className="text-lg font-semibold tracking-tight text-white">{symbol}</span>}
        {!editingSymbol && !stuck && <button type="button" onClick={() => setEditingSymbol(true)} className="text-[10px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline">Change</button>}
        <select aria-label="Plan account" value={account} disabled={!!stuck} onChange={(event) => setAccount(event.target.value)}
          className={`ml-auto max-w-[60%] rounded border bg-[#10151e] px-1.5 text-[11px] outline-none ${narrow ? "h-11" : "h-7"} ${account ? "border-slate-700 text-slate-200" : "border-amber-400/60 text-amber-200"}`}>
          {!account && <option value="">Choose account…</option>}
          {accounts.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
        </select>
      </div>
      {chartSymbol !== symbol && <p role="status" className="text-[10px] text-amber-300">The chart now shows {chartSymbol}. This plan stays on {symbol}; it is saved without a chart snapshot unless the main chart shows {symbol} again.</p>}
      {setupError && <p role="alert" className="text-[10px] text-amber-300">{setupError}</p>}
    </div>

    {editing && setup && <SetupEditor setup={setup} narrow={narrow} onSetup={onSetup} />}

    <fieldset disabled={!!stuck} className="space-y-3 px-3 py-2.5">
      <div role="group" aria-label="What you are taking">
        <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Taking</p>
        <div className="flex flex-wrap gap-1.5">
          {FAVORITE_SIDES.map(sideButton)}
          {(more || (side && MORE_SIDES.includes(side))) ? MORE_SIDES.map(sideButton)
            : <button type="button" aria-expanded={false} onClick={() => setMore(true)} className={`inline-flex items-center gap-1 rounded-md px-2 text-xs text-slate-500 hover:text-slate-300 ${narrow ? "min-h-11" : "min-h-8"}`}>More<ChevronDown size={12} /></button>}
        </div>
      </div>

      <div role="group" aria-label="Plan template">
        <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Plan</p>
        <div className="space-y-1.5">
          {templates.map((row) => <button key={row.id} type="button" aria-pressed={template === row.id} onClick={() => { setTemplate(row.id); setDiscretionary(false); setError(""); }}
            className={`block w-full rounded-md border px-2.5 py-1.5 text-left ${template === row.id ? "border-sky-400 bg-sky-400/10" : "border-slate-700 hover:bg-slate-800"}`}>
            <span className="block text-xs font-medium text-slate-100">{row.setup_label}</span>
            {/* The whole saved wording, visible before saving. */}
            <span className="mt-0.5 block whitespace-pre-wrap text-[11px] leading-4 text-slate-400">{row.wording}</span>
          </button>)}
          <button type="button" aria-pressed={discretionary} onClick={() => { setDiscretionary(true); setTemplate(null); setError(""); }}
            className={`block w-full rounded-md border px-2.5 py-1.5 text-left ${discretionary ? "border-sky-400 bg-sky-400/10" : "border-slate-700 hover:bg-slate-800"}`}>
            <span className="block text-xs font-medium text-slate-100">Discretionary / no explicit plan</span>
            <span className="mt-0.5 block text-[11px] leading-4 text-slate-500">Saved as intent with the plan unspecified.</span>
          </button>
          {!templates.length && <p className="text-[10px] leading-4 text-slate-500">No favorite templates yet. Add up to three with <Settings2 size={10} className="inline" aria-label="Capture setup" />; until then, use Discretionary or a voice note.</p>}
        </div>
      </div>

      <input aria-label="Plan note" placeholder="Short note (optional)" value={note} maxLength={500} onChange={(event) => setNote(event.target.value)}
        className={`w-full rounded border border-slate-700 bg-[#10151e] px-2 text-xs outline-none focus:border-sky-600 ${narrow ? "h-11" : "h-8"}`} />
      <div>
        <button type="button" aria-expanded={details} onClick={() => setDetails((v) => !v)} className="inline-flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300">Contract and size (optional)<ChevronDown size={11} className={details ? "rotate-180" : ""} /></button>
        {details && <div className="mt-1.5 grid grid-cols-3 gap-1.5">
          <input aria-label="Plan strike" type="number" step="any" min="0" placeholder="Strike" disabled={!side || !OPTION_SIDES.has(side)} value={strike} onChange={(event) => setStrike(event.target.value)} className="h-8 rounded border border-slate-700 bg-[#10151e] px-2 font-mono text-xs outline-none disabled:opacity-40" />
          <input aria-label="Plan expiration" type="date" disabled={!side || !OPTION_SIDES.has(side)} value={expiration} onChange={(event) => setExpiration(event.target.value)} className="h-8 rounded border border-slate-700 bg-[#10151e] px-1 text-[11px] outline-none disabled:opacity-40" />
          <input aria-label="Plan quantity" type="number" step="any" min="0" placeholder="Qty" value={quantity} onChange={(event) => setQuantity(event.target.value)} className="h-8 rounded border border-slate-700 bg-[#10151e] px-2 font-mono text-xs outline-none" />
        </div>}
      </div>
    </fieldset>

    <VoiceControls recorder={recorder} narrow={narrow} disabled={!!stuck || saving} ready={!!side && !!account}
      onNeedChoice={() => setError(!account ? "Choose the journal account first." : "Choose what you are taking first.")}
      onSave={() => recorder.recording && void submit(recorder.recording)} transcriber={transcriber} />

    <div className="sticky bottom-0 space-y-1.5 border-t border-slate-700/60 bg-[#121924] px-3 py-2">
      {error && <p role="alert" className="text-[11px] leading-4 text-amber-300">{error}</p>}
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[10px] text-slate-500">{accountLabel ? `${symbol} · ${accountLabel}` : `${symbol} · no account chosen`}</span>
        {stuck ? <button type="button" data-own-enter onClick={() => void deliver(stuck)} disabled={saving} className={`inline-flex items-center gap-1.5 rounded-md bg-amber-500/20 px-3 text-xs font-medium text-amber-100 hover:bg-amber-500/30 ${narrow ? "h-11" : "h-8"}`}>{saving && <Loader2 size={12} className="animate-spin" />}Retry</button>
          : <button type="button" data-own-enter onClick={() => void submit()} disabled={!canSave} title={canSave ? "Save plan (Enter)" : "Choose what you are taking and a plan"}
            className={`inline-flex items-center gap-1.5 rounded-md bg-sky-500 px-3 text-xs font-medium text-white hover:bg-sky-400 disabled:bg-slate-700 disabled:text-slate-400 ${narrow ? "h-11" : "h-8"}`}>{saving && <Loader2 size={12} className="animate-spin" />}{saving ? "Saving…" : "Save plan"}</button>}
      </div>
    </div>
  </div>;

  return createPortal(narrow
    ? <div className="fixed inset-0 z-[80] flex items-end bg-black/60" onClick={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>{panel}</div>
    // A desktop keeps the chart in view: the sheet sits at the right, over the side panel.
    : <div className="fixed right-3 top-14 z-[80]">{panel}</div>, document.body);
}

function VoiceControls({ recorder, narrow, disabled, ready, onNeedChoice, onSave, transcriber }: {
  recorder: ReturnType<typeof useRecorder>; narrow: boolean; disabled: boolean; ready: boolean; onNeedChoice(): void; onSave(): void;
  transcriber: CaptureSetup["transcriber"] | undefined;
}) {
  const { phase, mode, elapsed, recording, reason } = recorder;
  const live = phase === "recording" || phase === "asking";
  const begin = (how: "hold" | "tap") => { if (!ready) { onNeedChoice(); return; } void recorder.start(how); };
  return <section aria-label="Voice plan" className="space-y-1.5 border-t border-slate-700/60 px-3 py-2.5">
    <div className="flex items-center gap-2">
      {phase !== "review" && (live && mode === "tap"
        ? <button type="button" data-own-enter onClick={() => recorder.stop(true)} disabled={phase === "asking"}
          className={`inline-flex items-center gap-1.5 rounded-md bg-rose-500/20 px-3 text-xs font-medium text-rose-100 hover:bg-rose-500/30 ${narrow ? "h-11" : "h-9"}`}><Square size={12} />Stop &amp; save</button>
        : <button type="button" data-own-enter disabled={disabled} aria-label={live ? "Recording: release to save" : "Record voice plan"}
          title="Hold to record and release to save, or tap to start"
          onPointerDown={(event) => { if (event.button !== 0) return; event.preventDefault(); try { (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); } catch { /* a pointer the browser no longer tracks */ } begin("hold"); }}
          onPointerUp={() => recorder.release()}
          onPointerCancel={() => recorder.interrupt("Recording stopped when the press was interrupted. Save what was recorded, or discard it.")}
          onClick={(event) => { if (event.detail === 0) begin("tap"); }}
          onContextMenu={(event) => event.preventDefault()}
          className={`inline-flex touch-none select-none items-center gap-1.5 rounded-md border px-3 text-xs font-medium ${narrow ? "h-11" : "h-9"} ${live ? "border-rose-400 bg-rose-500/20 text-rose-100" : "border-slate-600 text-slate-200 hover:bg-slate-800"} disabled:opacity-40`}>
          <Mic size={13} className={phase === "recording" ? "animate-pulse text-rose-300" : ""} />{phase === "asking" ? "Allow the microphone…" : live ? "Release to save" : "Hold to record"}</button>)}
      {live && <span role="timer" aria-label="Recording time" className="font-mono text-xs text-rose-200">{secs(elapsed)} / 0:30</span>}
      {live && <button type="button" data-own-enter onClick={recorder.discard} className="ml-auto text-[11px] text-slate-400 hover:text-slate-200">Discard</button>}
      {!live && phase !== "review" && <span className="text-[10px] leading-4 text-slate-500">or tap it, then Stop &amp; save. Up to 30 seconds.</span>}
    </div>
    {phase === "review" && recording && <div className="space-y-1.5">
      <audio controls src={recording.url} className="h-8 w-full" aria-label="Recorded clip" />
      <div className="flex items-center gap-2">
        <button type="button" data-own-enter disabled={disabled} onClick={onSave} className={`inline-flex items-center gap-1.5 rounded-md bg-sky-500 px-3 text-xs font-medium text-white hover:bg-sky-400 disabled:opacity-40 ${narrow ? "h-11" : "h-8"}`}>Save recording</button>
        <button type="button" data-own-enter disabled={disabled} onClick={recorder.discard} className={`inline-flex items-center gap-1 rounded-md px-2 text-xs text-slate-400 hover:text-slate-200 ${narrow ? "h-11" : "h-8"}`}><Trash2 size={12} />Discard</button>
        <span className="ml-auto font-mono text-[10px] text-slate-500">{secs(recording.ms)}</span>
      </div>
    </div>}
    {reason && <p role="status" className="text-[11px] leading-4 text-amber-300">{reason}</p>}
    <p className="text-[10px] leading-4 text-slate-500">What am I taking, why here, and what would change my mind? Saving also requests a transcript. {transcriber?.note}</p>
  </section>;
}

/** One-time setup, outside the trading path: the default account and up to three favorite templates. */
function SetupEditor({ setup, narrow, onSetup }: { setup: CaptureSetup; narrow: boolean; onSetup(setup: CaptureSetup): void }) {
  const [draft, setDraft] = useState<{ id: string | null; setup_label: string; wording: string } | null>(null);
  const [problem, setProblem] = useState("");
  const run = (work: Promise<CaptureSetup>, after?: () => void) => work.then((next) => { onSetup(next); setProblem(""); after?.(); }).catch((error: Error) => setProblem(error.message));
  const field = `w-full rounded border border-slate-700 bg-[#10151e] px-2 text-xs outline-none focus:border-sky-600 ${narrow ? "min-h-11" : "min-h-8"}`;
  return <section aria-label="Capture setup" className="space-y-2 border-b border-slate-700/60 bg-[#0f141c] px-3 py-2.5">
    <label className="flex items-center gap-2 text-[11px] text-slate-400">Default account
      <select aria-label="Default account" value={setup.default_account_id ?? ""} onChange={(event) => run(saveDefaultAccount(event.target.value || null))}
        className={`ml-auto rounded border border-slate-700 bg-[#10151e] px-1.5 text-[11px] text-slate-200 ${narrow ? "h-11" : "h-7"}`}>
        <option value="">None (choose each time)</option>
        {setup.accounts.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
      </select>
    </label>
    <p className="text-[10px] uppercase tracking-wider text-slate-500">Favorite templates ({setup.templates.length}/{setup.max_templates})</p>
    {setup.templates.map((row) => <div key={row.id} className="flex items-start gap-1.5 text-[11px]">
      <div className="min-w-0 flex-1"><span className="font-medium text-slate-200">{row.setup_label}</span> <span className="text-[10px] text-slate-600">rev {row.revision}</span><p className="whitespace-pre-wrap text-slate-400">{row.wording}</p></div>
      <button type="button" aria-label={`Edit ${row.setup_label}`} onClick={() => setDraft({ id: row.id, setup_label: row.setup_label, wording: row.wording })} className="p-1 text-slate-500 hover:text-slate-200"><Pencil size={12} /></button>
      <button type="button" aria-label={`Remove ${row.setup_label}`} onClick={() => run(removeTemplate(row.id))} className="p-1 text-slate-500 hover:text-rose-300"><Trash2 size={12} /></button>
    </div>)}
    {draft ? <form className="space-y-1.5" onSubmit={(event) => { event.preventDefault(); run(draft.id ? editTemplate(draft.id, draft.setup_label, draft.wording) : addTemplate(draft.setup_label, draft.wording), () => setDraft(null)); }}>
      <input aria-label="Template name" autoFocus placeholder="Setup name, e.g. Reclaim" maxLength={40} value={draft.setup_label} onChange={(event) => setDraft({ ...draft, setup_label: event.target.value })} className={field} />
      <textarea aria-label="Template wording" placeholder="Your own invalidation or exit plan, e.g. Out on a 5m close back below the level." maxLength={400} rows={2} value={draft.wording}
        onChange={(event) => setDraft({ ...draft, wording: event.target.value })} className={`${field} py-1.5`} />
      <div className="flex gap-2"><button type="submit" className="h-8 rounded-md bg-slate-700 px-3 text-xs text-slate-100 hover:bg-slate-600">{draft.id ? "Save template" : "Add template"}</button>
        <button type="button" onClick={() => setDraft(null)} className="h-8 px-2 text-xs text-slate-400">Cancel</button></div>
      {draft.id && <p className="text-[10px] text-slate-500">Plans already saved keep the wording they were saved with.</p>}
    </form> : setup.templates.length < setup.max_templates && <button type="button" onClick={() => setDraft({ id: null, setup_label: "", wording: "" })}
      className="inline-flex items-center gap-1 text-[11px] text-sky-300 hover:text-sky-200"><Plus size={12} />Add template</button>}
    {problem && <p role="alert" className="text-[11px] text-amber-300">{problem}</p>}
  </section>;
}
