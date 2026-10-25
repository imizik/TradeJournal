"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2, Mic, X } from "lucide-react";
import { recordingType } from "@/lib/captures";
import { transcribeSpeech, type CopilotStatus } from "@/lib/copilot";
import { cn } from "@/lib/utils";

/** This browser only: whether a spoken message is sent as soon as it is transcribed (default) or left to review. */
const AUTO_SEND_KEY = "tradejournal.copilot.voice-auto-send.v1";
const CLIP_MS = 30_000, HOLD_MS = 400, CANCEL_PX = 80;
const secs = (ms: number) => `0:${String(Math.min(30, Math.floor(ms / 1000))).padStart(2, "0")}`;

type Phase = "idle" | "asking" | "recording" | "transcribing" | "error";
type Engine = "server" | "browser";
type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean; start(): void; stop(): void; abort(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null; onend: (() => void) | null; onstart: (() => void) | null;
};
type RecognitionClass = new () => Recognition;

function browserRecognition(): RecognitionClass | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionClass; webkitSpeechRecognition?: RecognitionClass };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const DENIED = "Microphone access is blocked. Allow it for this site in your browser’s settings (on iPhone: Settings › Safari › Microphone), or type the message.";

/**
 * Hold-to-talk for the copilot's composer. Press and hold the mic to talk, release to transcribe; a short tap
 * switches to tap-to-stop. Sliding off the button, Cancel, or a hidden page drops the clip. Audio goes to this
 * server's transcriber when it has one (``capabilities.transcriber``), else the browser's own recognition does the
 * listening; either way spoken tickers come back as symbols. With neither, there is no mic. ``onText`` gets the
 * words and whether to send them at once (the auto-send setting) or leave them in the box to review.
 */
export function useVoiceInput({ status, disabled, onText }: {
  status: CopilotStatus | null; disabled: boolean; onText(text: string, send: boolean): void;
}): { available: boolean; button: ReactNode; banner: ReactNode; setting: ReactNode } {
  const [phase, setPhase] = useState<Phase>("idle");
  const [mode, setMode] = useState<"hold" | "tap">("hold");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const [leaving, setLeaving] = useState(false);
  // Read after mount only: the setting renders once the lab's status has arrived in the browser.
  const [autoSend, setAutoSend] = useState(() => {
    try { return typeof window === "undefined" || window.localStorage.getItem(AUTO_SEND_KEY) !== "off"; } catch { return true; }
  });
  // ``take`` numbers each press; a cancel, a new press or closing the panel moves it on, so anything a superseded
  // take finishes later (the microphone arriving, the recorder stopping, a transcription) is dropped.
  const flags = useRef({ phase: "idle" as Phase, mode: "hold" as "hold" | "tap", released: false, take: 0, started: 0, x: 0, y: 0 });
  const media = useRef<{ stop(): void; abort(): void; timer: number } | null>(null);
  const pending = useRef<AbortController | null>(null);
  const deliver = useRef(onText);
  useEffect(() => { deliver.current = onText; });
  const configured = status?.enabled === true && status.capabilities?.transcriber?.configured === true;

  // The status is read in the browser, so on the server this is always null.
  const engine: Engine | null = !status?.enabled ? null : configured && recordingType() !== null ? "server" : browserRecognition() ? "browser" : null;

  const go = (next: Phase) => { flags.current.phase = next; setPhase(next); };
  const switchMode = (next: "hold" | "tap") => { flags.current.mode = next; setMode(next); };
  const fail = (why: string) => { setMessage(why); go("error"); };
  const autoSendRef = useRef(autoSend);
  useEffect(() => { autoSendRef.current = autoSend; });

  const finish = async (take: number, input: { audio: Blob; ms: number } | { text: string }) => {
    if ("text" in input && !input.text.trim()) { fail("Didn’t catch anything. Hold the mic and try again, or type."); return; }
    go("transcribing");
    const controller = new AbortController();
    pending.current = controller;
    let text: string;
    try {
      text = (await transcribeSpeech(input, controller.signal)).text.trim();
    } catch (error) {
      if (take !== flags.current.take) return;
      // The browser already heard the words; only the ticker clean-up failed.
      if ("text" in input) text = input.text.trim();
      else { fail(error instanceof Error ? error.message : "Transcription failed. Try again, or type."); return; }
    } finally {
      if (pending.current === controller) pending.current = null;
    }
    if (take !== flags.current.take) return;  // cancelled, or the panel closed, while it was transcribing
    if (!text) { fail("Didn’t catch anything. Hold the mic and try again, or type."); return; }
    go("idle");
    setMessage("");
    deliver.current(text, autoSendRef.current);
  }

  const timer = () => window.setInterval(() => {
    const ms = performance.now() - flags.current.started;
    setElapsed(ms);
    if (ms >= CLIP_MS) media.current?.stop();  // the 30-second limit sends what was said
  }, 100);

  const startServer = async (take: number) => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      if (take !== flags.current.take) return;
      const denied = error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
      fail(denied ? DENIED : "No microphone could be opened. Type the message instead.");
      return;
    }
    const close = () => stream.getTracks().forEach(track => track.stop());
    if (take !== flags.current.take) { close(); return; }
    const type = recordingType();
    let recorder: MediaRecorder;
    try {
      recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
      recorder.start(250);
    } catch {
      close();
      fail("This browser could not record from the microphone. Type the message instead.");
      return;
    }
    const chunks: Blob[] = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      close();
      if (media.current?.abort === abort) { window.clearInterval(media.current.timer); media.current = null; }
      if (take !== flags.current.take) return;
      if (!chunks.length) { fail("Recording stopped before any sound was captured. Try again."); return; }
      const ms = Math.min(CLIP_MS, Math.round(performance.now() - flags.current.started));
      void finish(take, { audio: new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" }), ms });
    };
    const abort = () => { if (recorder.state !== "inactive") recorder.stop(); };
    flags.current.started = performance.now();
    media.current = { stop: abort, abort, timer: timer() };
    afterStart();
  }

  const startBrowser = (take: number) => {
    const Recognizer = browserRecognition();
    if (!Recognizer) { fail("This browser cannot listen here. Type the message instead."); return; }
    const recognition = new Recognizer();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = false;
    const heard: string[] = [];
    let denied = false;
    recognition.onresult = event => {
      for (let i = event.resultIndex; i < event.results.length; i++) if (event.results[i].isFinal) heard.push(event.results[i][0].transcript);
    };
    recognition.onerror = event => {
      if (take !== flags.current.take) return;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") { denied = true; fail(DENIED); }
    };
    const abort = () => recognition.abort();
    recognition.onend = () => {
      if (media.current?.abort === abort) { window.clearInterval(media.current.timer); media.current = null; }
      if (denied || take !== flags.current.take) return;
      void finish(take, { text: heard.join(" ").trim() });
    };
    recognition.onstart = () => {
      if (take !== flags.current.take) { recognition.abort(); return; }
      flags.current.started = performance.now();
      if (media.current) media.current.timer = timer();
      afterStart();
    };
    media.current = { stop: () => recognition.stop(), abort, timer: 0 };
    try { recognition.start(); } catch { media.current = null; fail("This browser cannot listen here. Type the message instead."); }
  }

  const afterStart = () => {
    // The permission prompt took the press: keep listening, and let a tap end it.
    if (flags.current.mode === "hold" && flags.current.released) switchMode("tap");
    go("recording");
  }

  const start = (how: "hold" | "tap") => {
    if (!engine || disabled || ["asking", "recording", "transcribing"].includes(flags.current.phase)) return;
    const take = ++flags.current.take;
    flags.current.released = false;
    switchMode(how); setMessage(""); setElapsed(0); setLeaving(false);
    go("asking");
    if (engine === "server") void startServer(take); else startBrowser(take);
  }
  const stop = () => { media.current?.stop(); };
  /** Drops the take: a microphone still on its way is put down unused when it arrives, a transcription is ignored. */
  const cancel = () => {
    flags.current.take += 1;
    pending.current?.abort();
    if (media.current) { window.clearInterval(media.current.timer); media.current.abort(); media.current = null; }
    go("idle");
    setLeaving(false);
  }
  /** The press ended: a hold sends; a short press keeps listening in tap mode. */
  const release = () => {
    if (flags.current.mode !== "hold") return;
    if (flags.current.phase === "asking") { flags.current.released = true; return; }
    if (flags.current.phase !== "recording") return;
    if (performance.now() - flags.current.started < HOLD_MS) switchMode("tap");
    else stop();
  }

  const latest = useRef({ cancel });
  useEffect(() => { latest.current = { cancel }; });
  useEffect(() => {
    const state = flags.current;
    const holder = media;
    const transcribing = pending;
    const hidden = () => { if (document.hidden && holder.current) latest.current.cancel(); };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      // Closing the panel mid-clip or mid-transcription drops it; nothing is uploaded or sent unasked.
      state.take += 1;
      transcribing.current?.abort();
      if (holder.current) { window.clearInterval(holder.current.timer); holder.current.abort(); }
    };
  }, []);

  const available = engine !== null;
  const listening = phase === "recording" || phase === "asking";
  const button = !available ? null : (
    <button type="button" aria-label={listening ? (mode === "tap" ? "Stop and transcribe" : "Release to transcribe") : "Hold to talk"}
      aria-pressed={listening} disabled={disabled || phase === "transcribing"} data-testid="copilot-mic"
      onPointerDown={event => {
        if (event.button !== 0) return;
        event.preventDefault();
        if (listening && flags.current.mode === "tap") { stop(); return; }
        try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* synthetic pointer */ }
        Object.assign(flags.current, { x: event.clientX, y: event.clientY });
        start("hold");
      }}
      onPointerMove={event => {
        if (flags.current.mode !== "hold" || !["asking", "recording"].includes(flags.current.phase)) return;
        setLeaving(Math.hypot(event.clientX - flags.current.x, event.clientY - flags.current.y) > CANCEL_PX);
      }}
      onPointerUp={event => {
        if (flags.current.mode === "hold" && Math.hypot(event.clientX - flags.current.x, event.clientY - flags.current.y) > CANCEL_PX) cancel();
        else release();
      }}
      onPointerCancel={() => {
        // A first-use permission prompt can take the touch: keep listening and let a tap stop it.
        if (flags.current.mode === "hold" && flags.current.phase === "asking") flags.current.released = true;
        else if (flags.current.mode === "hold") cancel();
      }}
      onKeyDown={event => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (event.repeat) return;  // a held key is not a second tap
        if (listening) stop(); else start("tap");
      }}
      onContextMenu={event => event.preventDefault()}
      style={{ touchAction: "none", WebkitTouchCallout: "none", WebkitUserSelect: "none" }}
      className={cn("flex min-h-11 min-w-11 shrink-0 select-none items-center justify-center rounded border disabled:opacity-40",
        listening ? "border-rose-400 bg-rose-500/20 text-rose-200" : "text-muted-foreground hover:text-foreground")}>
      {phase === "transcribing" ? <Loader2 className="h-5 w-5 animate-spin" /> : <Mic className="h-5 w-5" />}
    </button>
  );

  const banner = !available || (phase === "idle" && !message) ? null : (
    <div role={phase === "error" ? "alert" : "status"} data-testid="copilot-voice-status"
      className={cn("flex items-center gap-2 rounded border px-3 py-2 text-xs",
        phase === "error" ? "border-rose-500/40 bg-rose-500/10 text-rose-200" : "bg-[#0f1520] text-foreground")}>
      {listening ? (
        <>
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-rose-400" aria-hidden />
          <span className="font-mono tabular-nums">{phase === "asking" ? "0:00" : secs(elapsed)}</span>
          <span className="min-w-0 flex-1 text-muted-foreground">
            {phase === "asking" ? "Waiting for the microphone…" : leaving ? "Let go to cancel" : mode === "tap" ? "Listening · tap the mic to stop" : "Listening · release to transcribe, slide away to cancel"}
          </span>
          <button type="button" onClick={cancel} className="inline-flex min-h-11 shrink-0 items-center gap-1 rounded border px-3 text-xs">
            <X className="h-3.5 w-3.5" aria-hidden /> Cancel
          </button>
        </>
      ) : phase === "transcribing" ? (
        <span className="text-muted-foreground">Transcribing…</span>
      ) : (
        <>
          <span className="min-w-0 flex-1">{message}</span>
          <button type="button" onClick={() => { setMessage(""); go("idle"); }} aria-label="Dismiss" className="min-h-11 min-w-11 shrink-0"><X className="mx-auto h-4 w-4" /></button>
        </>
      )}
    </div>
  );

  const setting = !available ? null : (
    <label className="inline-flex min-h-11 items-center gap-2 text-xs text-muted-foreground">
      <input type="checkbox" checked={autoSend} className="h-4 w-4"
        onChange={event => {
          setAutoSend(event.target.checked);
          try { window.localStorage.setItem(AUTO_SEND_KEY, event.target.checked ? "on" : "off"); } catch { /* this visit only */ }
        }} />
      Auto-send what I say
    </label>
  );

  return { available, button, banner, setting };
}
