import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";

test("local lab proxy fails closed and never forwards browser credentials or parameters", async () => {
  const source = readFileSync(path.join(__dirname, "../app/api/level2-lab/session/route.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  let profile = "private_legacy";
  const output: { GET?: (request: Request) => Promise<Response>; POST?: (request: Request) => Promise<Response> } = {};
  new Function("require", "exports", compiled)(() => ({ accessConfig: () => ({ profile }) }), output);
  const originalFetch = globalThis.fetch;
  const priorEnabled = process.env.TJ_MOOMOO_LAB_ENABLED, priorToken = process.env.TJ_MOOMOO_LAB_TOKEN;
  const calls: { target: string; init?: RequestInit }[] = [];
  globalThis.fetch = async (target, init) => {
    calls.push({ target: String(target), init });
    return new Response('{"event":"status","phase":"closed"}\n', { headers: { "Content-Type": "application/x-ndjson" } });
  };
  const request = (url = "http://127.0.0.1:3197/api/level2-lab/session", origin = "http://127.0.0.1:3197", body?: string) => new Request(url, {
    method: "POST", headers: { Host: new URL(url).host, origin, "Content-Type": "application/x-level2-start", Authorization: "DO-NOT-FORWARD", Cookie: "DO-NOT-FORWARD" }, body,
  });
  try {
    delete process.env.TJ_MOOMOO_LAB_ENABLED;
    delete process.env.TJ_MOOMOO_LAB_TOKEN;
    expect(await (await output.GET!(new Request("http://127.0.0.1:3197/api/level2-lab/session", {headers:{Host:"127.0.0.1:3197"}}))).json()).toEqual({ enabled: false });
    expect((await output.POST!(request())).status).toBe(503);
    process.env.TJ_MOOMOO_LAB_ENABLED = "true";
    process.env.TJ_MOOMOO_LAB_TOKEN = "invented-loopback-token-00000000000000";
    profile = "assistant";
    expect((await output.POST!(request())).status).toBe(403);
    profile = "private_legacy";
    expect((await output.POST!(request(undefined, "https://evil.invalid"))).status).toBe(400);
    expect((await output.POST!(request("https://tradejournal.invalid/api/level2-lab/session"))).status).toBe(503);
    expect((await output.POST!(request("http://127.0.0.1:3197/api/level2-lab/session?symbol=US.AAPL"))).status).toBe(400);
    expect((await output.POST!(request(undefined, undefined, "{}"))).status).toBe(400);
    const remoteHost = request(); remoteHost.headers.set("host", "remote.invalid:3197");
    expect((await output.POST!(remoteHost)).status).toBe(503);
    expect(calls).toHaveLength(0);
    const response = await output.POST!(request());
    expect(await response.text()).toContain('"closed"');
    expect(calls).toHaveLength(1);
    expect(calls[0].target).toBe("http://127.0.0.1:8196/session");
    expect(calls[0].init?.redirect).toBe("manual");
    expect(calls[0].init?.body).toBeUndefined();
    const forwarded = JSON.stringify(calls[0].init?.headers);
    expect(forwarded).not.toContain("DO-NOT-FORWARD");
    expect(forwarded).toContain("Bearer invented-loopback-token");
  } finally {
    globalThis.fetch = originalFetch;
    if (priorEnabled === undefined) delete process.env.TJ_MOOMOO_LAB_ENABLED; else process.env.TJ_MOOMOO_LAB_ENABLED = priorEnabled;
    if (priorToken === undefined) delete process.env.TJ_MOOMOO_LAB_TOKEN; else process.env.TJ_MOOMOO_LAB_TOKEN = priorToken;
  }
});

test("proxy propagates request abort, response cancel and its 40-second bound upstream", async () => {
  const source = readFileSync(path.join(__dirname, "../app/api/level2-lab/session/route.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const output: { POST?: (request: Request) => Promise<Response> } = {};
  new Function("require", "exports", compiled)(() => ({ accessConfig: () => ({ profile: "private_legacy" }) }), output);
  const originalFetch = globalThis.fetch, originalTimeout = globalThis.setTimeout;
  const priorEnabled = process.env.TJ_MOOMOO_LAB_ENABLED, priorToken = process.env.TJ_MOOMOO_LAB_TOKEN;
  let fireDeadline: (() => void) | undefined;
  globalThis.setTimeout = ((callback: () => void, delay?: number) => {
    if (delay === 40_000) { fireDeadline = callback; return originalTimeout(callback, 1_000_000); }
    return originalTimeout(callback, delay);
  }) as typeof setTimeout;
  process.env.TJ_MOOMOO_LAB_ENABLED = "true";
  process.env.TJ_MOOMOO_LAB_TOKEN = "invented-loopback-token-00000000000000";
  let upstreamSignal: AbortSignal | undefined;
  let cancelled = 0;
  globalThis.fetch = async (_target, init) => {
    upstreamSignal = init?.signal as AbortSignal;
    return new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('{"event":"status","phase":"connecting"}\n')); },
      cancel() { cancelled += 1; },
    }), { headers: { "Content-Type": "application/x-ndjson" } });
  };
  const request = (signal?: AbortSignal) => new Request("http://127.0.0.1:3197/api/level2-lab/session", {
    method: "POST", signal, headers: { Host: "127.0.0.1:3197", Origin: "http://127.0.0.1:3197", "Content-Type": "application/x-level2-start" },
  });
  try {
    const incoming = new AbortController();
    let response = await output.POST!(request(incoming.signal));
    expect(upstreamSignal?.aborted).toBe(false);
    incoming.abort();
    expect(upstreamSignal?.aborted).toBe(true);
    await response.body!.cancel();
    expect(cancelled).toBe(1);
    response = await output.POST!(request());
    expect(upstreamSignal?.aborted).toBe(false);
    await response.body!.cancel();
    expect(upstreamSignal?.aborted).toBe(true);
    expect(cancelled).toBe(2);
    response = await output.POST!(request());
    expect(upstreamSignal?.aborted).toBe(false);
    expect(fireDeadline).toBeDefined();
    fireDeadline!();
    expect(upstreamSignal?.aborted).toBe(true);
    await response.body!.cancel();
    expect(cancelled).toBe(3);
  } finally {
    globalThis.fetch = originalFetch; globalThis.setTimeout = originalTimeout;
    if (priorEnabled === undefined) delete process.env.TJ_MOOMOO_LAB_ENABLED; else process.env.TJ_MOOMOO_LAB_ENABLED = priorEnabled;
    if (priorToken === undefined) delete process.env.TJ_MOOMOO_LAB_TOKEN; else process.env.TJ_MOOMOO_LAB_TOKEN = priorToken;
  }
});
