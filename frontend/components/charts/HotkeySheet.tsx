"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { HOTKEY_HELP, HOTKEY_JOINERS } from "@/lib/hotkeys";

/**
 * The `?` cheat sheet. It lists `HOTKEY_HELP`, the same table the workspace
 * handles keys from. `?` and Escape close it (the workspace owns those keys).
 */
export default function HotkeySheet({ onClose }: { onClose(): void }) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { dialog.current?.focus(); }, []);
  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:items-start sm:px-4 sm:pb-0 sm:pt-[6vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Keyboard shortcuts"
        className="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-700 bg-[#121924] shadow-2xl outline-none">
        <div className="flex items-center justify-between border-b border-slate-700/60 px-3 py-2.5">
          <h2 className="text-xs font-medium text-slate-200">Keyboard shortcuts</h2>
          <button className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-100" aria-label="Close keyboard shortcuts" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="space-y-2 px-3 py-2.5">
          {HOTKEY_HELP.map(({ group, rows }) => <table key={group} className="w-full text-[11px]">
            <caption className="pb-1 text-left text-[10px] font-medium uppercase tracking-wider text-slate-500">{group}</caption>
            <tbody>{rows.map((row) => <tr key={`${group}-${row.keys}`} className="border-t border-slate-800/80">
              <td aria-label={row.keys} className="w-[45%] py-1 pr-3 align-top"><span aria-hidden className="flex flex-wrap items-center gap-1">{row.keys.split(" ").map((word, index) => HOTKEY_JOINERS.has(word)
                ? <span key={index} className="text-[10px] text-slate-500">{word}</span>
                : <kbd key={index} className="min-w-5 rounded border border-slate-700 bg-slate-800/70 px-1.5 py-px text-center font-mono text-[10px] text-slate-200">{word}</kbd>)}</span></td>
              <td className="py-1 text-slate-300">{row.does}</td>
            </tr>)}</tbody>
          </table>)}
          <p className="text-[10px] leading-4 text-slate-500">Shortcuts pause while you type in a field or a dialog is open. Alt is Option on a Mac. The interval buttons, the watchlist arrows, each chart&rsquo;s latest-candles button, a selected level&rsquo;s Delete button and the Undo and Redo buttons do the same by touch.</p>
        </div>
      </div>
    </div>
  );
}
