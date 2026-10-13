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
    // One plain-ticker `symbol` is the only argument; anything else is refused before forwarding.
    for (const query of ["symbol=US.AAPL", "symbol=aapl", "symbol=AAPL&x=1", "symbol=AAPL&symbol=MSFT", "symbol=AA%2FPL", "x=AAPL", "symbol=TOOLONG"])
      expect((await output.POST!(request(`http://127.0.0.1:3197/api/level2-lab/session?${query}`))).status).toBe(400);
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
    await (await output.POST!(request("http://127.0.0.1:3197/api/level2-lab/session?symbol=BRK.B"))).text();
    expect(calls[1].target).toBe("http://127.0.0.1:8196/session?symbol=BRK.B");
    expect((await output.GET!(new Request("http://127.0.0.1:3197/api/level2-lab/session?symbol=AAPL", { headers: { Host: "127.0.0.1:3197" } }))).status).toBe(400);
  } finally {
    globalThis.fetch = originalFetch;
    if (priorEnabled === undefined) delete process.env.TJ_MOOMOO_LAB_ENABLED; else process.env.TJ_MOOMOO_LAB_ENABLED = priorEnabled;
    if (priorToken === undefined) delete process.env.TJ_MOOMOO_LAB_TOKEN; else process.env.TJ_MOOMOO_LAB_TOKEN = priorToken;
  }
});

test("proxy propagates request abort, response cancel and its eight-hour backstop upstream", async () => {
  const source = readFileSync(path.join(__dirname, "../app/api/level2-lab/session/route.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const output: { POST?: (request: Request) => Promise<Response> } = {};
  new Function("require", "exports", compiled)(() => ({ accessConfig: () => ({ profile: "private_legacy" }) }), output);
  const originalFetch = globalThis.fetch, originalTimeout = globalThis.setTimeout;
  const priorEnabled = process.env.TJ_MOOMOO_LAB_ENABLED, priorToken = process.env.TJ_MOOMOO_LAB_TOKEN;
  let fireDeadline: (() => void) | undefined;
  globalThis.setTimeout = ((callback: () => void, delay?: number) => {
    if (delay === 8 * 3600_000 + 60_000) { fireDeadline = callback; return originalTimeout(callback, 1_000_000); }
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


test("private HTTPS transport pins its configured owner origin and denies assistants and missing owner sessions", async () => {
  const source = readFileSync(path.join(__dirname, "../app/api/level2-lab/session/route.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const origin = "https://fixture.tail000.ts.net";
  let profile = "private_legacy", owner = true;
  const output: { GET?: (request: Request) => Promise<Response>; POST?: (request: Request) => Promise<Response> } = {};
  new Function("require", "exports", compiled)(() => ({ accessConfig: () => ({ profile, origin }),
    currentAccess: async () => owner ? { enabled: true, owner: true } : null }), output);
  const names = ["TJ_MOOMOO_LAB_ENABLED", "TJ_MOOMOO_LAB_TOKEN", "TJ_MOOMOO_WEB_ORIGIN"];
  const prior = names.map(name => process.env[name]);
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response('{"event":"status","phase":"closed"}\n', { headers: { "Content-Type": "application/x-ndjson" } }); };
  const request = (host = "fixture.tail000.ts.net", suppliedOrigin = origin) => new Request("http://localhost:3000/api/level2-lab/session", {
    method: "POST", headers: { Host: host, Origin: suppliedOrigin, "Content-Type": "application/x-level2-start" },
  });
  try {
    process.env.TJ_MOOMOO_LAB_ENABLED = "true";
    process.env.TJ_MOOMOO_LAB_TOKEN = "invented-loopback-token-00000000000000";
    process.env.TJ_MOOMOO_WEB_ORIGIN = origin;
    expect((await output.POST!(request("evil.invalid"))).status).toBe(503);
    expect((await output.POST!(request(undefined, "https://evil.invalid"))).status).toBe(400);
    expect((await output.POST!(request(undefined, "null"))).status).toBe(400);
    expect((await output.POST!(request("127.0.0.1:3000", "http://127.0.0.1:3000"))).status).toBe(503);
    profile = "assistant";
    expect((await output.POST!(request())).status).toBe(403);
    expect((await output.GET!(new Request(origin + "/api/level2-lab/session", { headers: { Host: "fixture.tail000.ts.net" } }))).status).toBe(403);
    profile = "owner"; owner = false;
    expect((await output.POST!(request())).status).toBe(403);
    expect(calls).toBe(0);
    owner = true;
    expect(await (await output.POST!(request())).text()).toContain('"closed"');
    profile = "private_legacy";
    expect(await (await output.POST!(request())).text()).toContain('"closed"');
    expect(calls).toBe(2);
    for (const invalid of ["https://evil.invalid", origin + "/", "http://fixture.tail000.ts.net", "https://fixture.tail000.ts.net:8443", "https://user@fixture.tail000.ts.net"]) {
      process.env.TJ_MOOMOO_WEB_ORIGIN = invalid;
      expect((await output.POST!(request())).status).toBe(503);
    }
    expect(calls).toBe(2);
  } finally {
    globalThis.fetch = originalFetch;
    names.forEach((name, index) => { if (prior[index] === undefined) delete process.env[name]; else process.env[name] = prior[index]; });
  }
});

test("recorded depth proxy forwards only fixed GET parameters to the loopback bridge", async () => {
  const source = readFileSync(path.join(__dirname, "../app/api/level2-lab/depth/route.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  let profile = "private_legacy";
  const output: { GET?: (request: Request) => Promise<Response> } = {};
  new Function("require", "exports", compiled)(() => ({ accessConfig: () => ({ profile }) }), output);
  const originalFetch = globalThis.fetch;
  const priorEnabled = process.env.TJ_MOOMOO_LAB_ENABLED, priorToken = process.env.TJ_MOOMOO_LAB_TOKEN;
  const calls: { target: string; init?: RequestInit }[] = [];
  globalThis.fetch = async (target, init) => { calls.push({ target: String(target), init }); return Response.json({ recorded: false }); };
  const get = (query: string) => output.GET!(new Request(`http://127.0.0.1:3197/api/level2-lab/depth${query}`, { headers: { Host: "127.0.0.1:3197", Cookie: "DO-NOT-FORWARD" } }));
  try {
    delete process.env.TJ_MOOMOO_LAB_ENABLED;
    expect((await get("?symbol=NVDA")).status).toBe(503);
    process.env.TJ_MOOMOO_LAB_ENABLED = "true";
    process.env.TJ_MOOMOO_LAB_TOKEN = "invented-loopback-token-00000000000000";
    profile = "assistant";
    expect((await get("?symbol=NVDA")).status).toBe(403);
    profile = "private_legacy";
    for (const query of ["?symbol=nvda", "?symbol=NVDA&kind=x", "?symbol=NVDA&minutes=0", "?symbol=NVDA&bucket=5", "?symbol=NVDA&x=1", "?symbol=NVDA&symbol=MU", "?symbol=../x"])
      expect((await get(query)).status).toBe(400);
    expect(calls).toHaveLength(0);
    expect(await (await get("?symbol=BRK.B&kind=mpid&minutes=240&bucket=30")).json()).toEqual({ recorded: false });
    expect(calls[0].target).toBe("http://127.0.0.1:8196/depth?symbol=BRK.B&kind=mpid&minutes=240&bucket=30");
    expect(JSON.stringify(calls[0].init?.headers)).not.toContain("DO-NOT-FORWARD");
  } finally {
    globalThis.fetch = originalFetch;
    if (priorEnabled === undefined) delete process.env.TJ_MOOMOO_LAB_ENABLED; else process.env.TJ_MOOMOO_LAB_ENABLED = priorEnabled;
    if (priorToken === undefined) delete process.env.TJ_MOOMOO_LAB_TOKEN; else process.env.TJ_MOOMOO_LAB_TOKEN = priorToken;
  }
});
