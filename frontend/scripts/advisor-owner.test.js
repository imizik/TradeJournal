// Isolated BFF boundary proof; no browser/provider/owner credentials or ledger writes.
/* eslint-disable @typescript-eslint/no-require-imports -- Node's built-in test harness loads the actual server module with isolated auth dependencies. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const Module = require('node:module');
const ts = require('typescript');
const originalFetch = global.fetch;
const source = path.resolve(__dirname, '../lib/advisorOwner.ts');
const profile = { value: 'owner' };
const transformed = ts.transpileModule(fs.readFileSync(source, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
const loaded = new Module(source, module);
loaded.filename = source; loaded.paths = module.paths;
const regular = loaded.require.bind(loaded);
loaded.require = name => name === 'server-only' ? {} : name === './accessServer' ? {
  accessConfig: () => ({ profile: profile.value, target: 'http://127.0.0.1:8129' }),
  upstreamHeaders: incoming => new Headers({ cookie: incoming.get('cookie') ?? '', 'x-tj-gateway': 'invented-owner-gateway' }),
} : regular(name);
loaded._compile(transformed, source);
const read = () => loaded.exports.advisorOwner(new Request('http://owner/api/advisor-owner', { headers: { cookie: 'invented-owner-session' } }));
const body = JSON.stringify({ schema_version: 'advisor-owner-review-v1', demo_only: true, request: { immutable: 'invented' }, receipt: null });

async function fixture(run) {
  const before = { ...process.env };
  const directory = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'tj-bff-'));
  const socket = path.join(directory, 'owner.sock');
  const server = http.createServer();
  await new Promise(resolve => server.listen(socket, resolve)); fs.chmodSync(socket, 0o600);
  Object.assign(process.env, { TJ_ADVISOR_OWNER_ENABLED: 'true', TJ_ADVISOR_OWNER_SOCKET: socket, TJ_ADVISOR_OWNER_SOCKET_UID: String(process.getuid()) });
  profile.value = 'owner';
  let authCalls = 0;
  global.fetch = async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:8129/access/me'); assert.equal(options.cache, 'no-store');
    authCalls += 1; return Response.json({ enabled: true, owner: true });
  };
  try { await run({ server, socket, calls: () => authCalls }); }
  finally {
    global.fetch = originalFetch; profile.value = 'owner';
    for (const name of Object.keys(process.env)) if (!(name in before)) delete process.env[name]; Object.assign(process.env, before);
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test('BFF returns identical bytes over fixed Unix GET and forwards no credentials', async () => fixture(async ({ server, calls }) => {
  server.on('request', (request, response) => {
    assert.equal(request.method, 'GET'); assert.equal(request.url, '/owner/advisor');
    for (const key of ['cookie', 'authorization', 'x-tj-gateway', 'x-tj-service', 'x-tj-bootstrap']) assert.equal(request.headers[key], undefined);
    response.setHeader('Content-Type', 'application/json'); response.end(body);
  });
  const response = await read(); assert.equal(response.status, 200); assert.equal(await response.text(), body); assert.equal(calls(), 2);
}));

test('legacy and assistant profiles cannot connect; disabled owner binding stays dormant', async () => fixture(async ({ server }) => {
  let requests = 0; server.on('request', () => { requests += 1; });
  for (const [value, expected] of [['private_legacy', 503], ['assistant', 403]]) { profile.value = value; assert.equal((await read()).status, expected); }
  profile.value = 'owner'; process.env.TJ_ADVISOR_OWNER_ENABLED = 'false'; assert.equal((await read()).status, 503); assert.equal(requests, 0);
}));

test('unauthorized owner session cannot connect and inflight revocation suppresses payload', async () => fixture(async ({ server }) => {
  let requests = 0; server.on('request', (_, response) => { requests += 1; response.setHeader('Content-Type', 'application/json'); response.end(body); });
  global.fetch = async () => new Response('', { status: 401 });
  assert.equal((await read()).status, 401); assert.equal(requests, 0);
  let calls = 0; global.fetch = async () => ++calls === 1 ? Response.json({ enabled: true, owner: true }) : new Response('', { status: 401 });
  const response = await read(); assert.equal(response.status, 401); assert.equal(requests, 1); assert.equal(calls, 2); assert.doesNotMatch(await response.text(), /immutable/);
}));

test('socket inode drift during read, writable parent, and symlink refuse', async () => fixture(async ({ server, socket }) => {
  server.on('request', (_, response) => { fs.renameSync(socket, socket + '.old'); response.setHeader('Content-Type', 'application/json'); response.end(body); });
  assert.equal((await read()).status, 503);
  fs.renameSync(socket + '.old', socket);
  fs.chmodSync(path.dirname(socket), 0o777); assert.equal((await read()).status, 503); fs.chmodSync(path.dirname(socket), 0o700);
  fs.renameSync(socket, socket + '.old'); fs.symlinkSync(socket + '.old', socket); assert.equal((await read()).status, 503);
}));

test('oversize, redirect and malformed reader responses fail without retry/fallback', async () => {
  for (const mode of ['oversize', 'redirect', 'malformed']) await fixture(async ({ server }) => {
    let requests = 0;
    server.on('request', (_, response) => { requests += 1; response.setHeader('Content-Type', 'application/json'); if (mode === 'redirect') { response.statusCode = 302; response.setHeader('Location', 'http://external.invalid'); } response.end(mode === 'oversize' ? 'x'.repeat(65537) : mode === 'malformed' ? '{}' : body); });
    assert.equal((await read()).status, 503); assert.equal(requests, 1);
  });
});
