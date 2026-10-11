"use client";
import { apiUrl } from "@/lib/api";
class ResearchError extends Error { constructor(message: string, readonly status: number) { super(message); } }
export async function command<T>(action: string, args: object = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl("/research-studio/command"), {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, arguments: args}), signal, cache: "no-store"});
  const data = await response.json(); if (!response.ok) throw new ResearchError(data.detail || "Research unavailable", response.status); return data;
}
export async function prepared<T>(action: string, args: object, signal?: AbortSignal): Promise<T> {
  const deadline = performance.now() + 65000;
  while (true) {
    try { return await command<T>(action, args, signal); }
    catch (error) {
      if (!(error instanceof ResearchError) || error.status !== 409 || !error.message.includes("preparation is busy") || signal?.aborted || performance.now() >= deadline) throw error;
      await new Promise<void>(resolve => setTimeout(resolve, 100));
      if (signal?.aborted) throw new Error("Preview superseded");
    }
  }
}
