"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { SPEAK_RATES, rememberSpeak, rememberSpeakRate, speakOn, speakRate, speechText, type LabMessage } from "@/lib/copilot";
import { cn } from "@/lib/utils";

const synth = () => typeof window !== "undefined" && window.speechSynthesis && typeof window.SpeechSynthesisUtterance === "function" ? window.speechSynthesis : null;

/** The device's default English voice, else its first English one; the browser picks when it lists none yet. */
function englishVoice(voices: SpeechSynthesisVoice[]) {
  const english = voices.filter(voice => /^en(-|_|$)/i.test(voice.lang));
  return english.find(voice => voice.default) ?? english[0] ?? null;
}

// iPhone Safari speaks from a timer only after the page has spoken once from a tap: the first tap primes it silently.
let primed = false;
function prime() {
  const speech = synth();
  if (primed || !speech) return;
  primed = true;
  const silent = new SpeechSynthesisUtterance(" ");
  silent.volume = 0;
  speech.speak(silent);
}

/**
 * Read it back: with the speaker on, each finished answer (``turn`` counts the turns whose ``done`` arrived, with
 * ``message`` that turn's answer) is spoken by the browser's own speech synthesis, never a server. A new turn
 * (``busy``), the mic (``listening``), a hidden page or a tap on the speaker stops it at once, so speech and recording
 * never overlap (``stop`` lets the mic silence it before it starts listening). Without speech synthesis there is no speaker. The on/off and speed are this browser's settings.
 */
export function useSpeakAnswer({ ready, turn, message, busy, listening, disabled }: {
  ready: boolean; turn: number; message: LabMessage | null; busy: boolean; listening: boolean; disabled: boolean;
}): { available: boolean; speaking: boolean; stop(): void; button: ReactNode; setting: ReactNode } {
  // The settings are read in the browser; the speaker renders only once ``ready`` (the lab's status, which only the
  // browser reads), so the server's render and the first client render agree.
  const [on, setOn] = useState(() => typeof window !== "undefined" && speakOn());
  const [rate, setRate] = useState(() => typeof window === "undefined" ? 1 : speakRate());
  const [speaking, setSpeaking] = useState(false);
  const supported = ready && synth() !== null;

  const live = useRef({ on, rate, listening, message });
  const reading = useRef<SpeechSynthesisUtterance | null>(null); // held so it is not collected mid-sentence
  useEffect(() => { live.current = { on, rate, listening, message }; });

  // Cancelling ends the utterance with an error event, which clears ``speaking``.
  const stop = () => synth()?.cancel();

  useEffect(() => {
    const speech = synth();
    const { on: speak, rate: pace, listening: recording, message: answer } = live.current;
    if (!turn || !speech || !speak || recording || !answer || document.hidden) return;
    const text = speechText(answer);
    if (!text) return;
    speech.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = englishVoice(speech.getVoices());
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang ?? "en-US";
    utterance.rate = pace;
    // A cancelled answer's late error must not clear the state of the one that replaced it.
    utterance.onend = utterance.onerror = () => { if (reading.current === utterance) { reading.current = null; setSpeaking(false); } };
    reading.current = utterance;
    setSpeaking(true);
    speech.speak(utterance);
  }, [turn]);

  // A new turn or the mic stops the answer being read.
  useEffect(() => { if (busy || listening) stop(); }, [busy, listening]);

  useEffect(() => {
    const hidden = () => { if (document.hidden) stop(); };
    document.addEventListener("visibilitychange", hidden);
    return () => { document.removeEventListener("visibilitychange", hidden); synth()?.cancel(); };
  }, []);

  useEffect(() => {
    if (!on || !supported || primed) return;
    document.addEventListener("pointerdown", prime, { capture: true, once: true });
    return () => document.removeEventListener("pointerdown", prime, { capture: true });
  }, [on, supported]);

  const available = supported;
  const button = !available ? null : (
    <button type="button" data-testid="copilot-speak" disabled={disabled && !speaking}
      aria-label={speaking ? "Stop reading aloud" : "Read answers aloud"} aria-pressed={on}
      title={speaking ? "Stop reading this answer" : on ? "Answers are read aloud; tap to turn off" : "Read answers aloud"}
      onClick={() => {
        prime();
        if (speaking) { stop(); setSpeaking(false); return; }
        setOn(!on);
        rememberSpeak(!on);
      }}
      className={cn("flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded border disabled:opacity-40",
        on ? "border-sky-400/60 bg-sky-500/15 text-sky-200" : "text-muted-foreground hover:text-foreground")}>
      {on ? <Volume2 className={cn("h-5 w-5", speaking && "animate-pulse")} /> : <VolumeX className="h-5 w-5" />}
    </button>
  );

  const setting = !available || !on ? null : (
    <label className="inline-flex min-h-11 items-center gap-2 text-xs text-muted-foreground">
      Voice speed
      <select aria-label="Voice speed" value={rate} className="min-h-11 rounded border bg-background px-1.5 text-xs text-foreground sm:min-h-0"
        onChange={event => { const next = Number(event.target.value); setRate(next); rememberSpeakRate(next); }}>
        {SPEAK_RATES.map(r => <option key={r} value={r}>{r === 1 ? "1.0×" : `${r}×`}</option>)}
      </select>
    </label>
  );

  return { available, speaking, stop, button, setting };
}
