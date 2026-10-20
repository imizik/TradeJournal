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
  accessConfig: () => ({ profile: profile.value, target: 'http://127.0.0.1:8129', origin: 'http://owner' }),
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

const status = () => loaded.exports.advisorOwnerStatus(new Request('http://owner/api/advisor-owner/status', { headers: { cookie: 'invented-owner-session' } }));
const statusBody = JSON.stringify({ schema_version: 'advisor-owner-status-v1', checked_at: '2026-10-11T12:00:00+00:00', keys: { state: 'fresh', expires_at: '2026-10-11T13:00:00+00:00' }, advisor: { state: 'enabled' }, assignment: { state: 'pending', expires_at: '2026-10-11T12:30:00+00:00' }, last_save_at: null, last_read_at: null });

test('status BFF reads only the fixed status path with the same owner session and shape checks', async () => fixture(async ({ server, calls }) => {
  let reply = statusBody;
  server.on('request', (request, response) => {
    assert.equal(request.method, 'GET'); assert.equal(request.url, '/owner/advisor/status');
    for (const key of ['cookie', 'authorization', 'x-tj-gateway']) assert.equal(request.headers[key], undefined);
    response.setHeader('Content-Type', 'application/json'); response.end(reply);
  });
  const response = await status(); assert.equal(response.status, 200); assert.equal(await response.text(), statusBody); assert.equal(calls(), 2);
  reply = body; const wrong = await status(); assert.equal(wrong.status, 503); assert.match(await wrong.text(), /connection status unavailable/);
  assert.equal((await loaded.exports.advisorOwnerStatus(new Request('http://owner/api/advisor-owner/status?state=x'))).status, 400);
  profile.value = 'assistant'; assert.equal((await status()).status, 403);
}));


const managerSource = path.resolve(__dirname, '../lib/advisorAssignments.ts');
const managerModule = new Module(managerSource, module);
managerModule.filename = managerSource; managerModule.paths = module.paths;
managerModule.require = name => name === './advisorOwner' ? loaded.exports : loaded.require(name);
managerModule._compile(ts.transpileModule(fs.readFileSync(managerSource, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText, managerSource);
const createBody = { operation_id: '00000000-0000-0000-0000-000000000001', question: 'Invented question?', user_plan: 'Wait', invented_only: true };
const managerResponse = JSON.stringify({ schema_version: 'advisor_assignments_v1', demo_only: true, assignments: [], selected: null });
const manage = (overrides = {}) => managerModule.exports.advisorAssignments(new Request('http://owner/api/advisor-assignments', {
  method: 'POST', headers: { cookie: 'fixture-owner', Origin: 'http://owner', 'x-tj-csrf': 'fixture-csrf', 'Content-Type': 'application/json' }, body: JSON.stringify(createBody), ...overrides,
}));
function managerSocket(socket) {
  const next = path.join(path.dirname(socket), 'backend.sock'); fs.renameSync(socket, next);
  Object.assign(process.env, { TJ_ADVISOR_MANAGEMENT_ENABLED: 'true', TJ_ADVISOR_MANAGER_SOCKET: next, TJ_ADVISOR_MANAGER_SOCKET_UID: String(process.getuid()) });
  global.fetch = async () => Response.json({ enabled: true, owner: true, csrf: 'fixture-csrf' });
}

test('management validates owner CSRF and origin before Unix writes; forwards only bounded action', async () => fixture(async ({ server, socket }) => {
  managerSocket(socket); let writes = 0;
  server.on('request', (request, response) => {
    writes++; assert.equal(request.method, 'POST'); assert.equal(request.url, '/owner/advisor/assignments');
    for (const key of ['cookie', 'authorization', 'x-tj-gateway', 'x-tj-csrf', 'origin']) assert.equal(request.headers[key], undefined);
    let received = ''; request.on('data', chunk => { received += chunk; });
    request.on('end', () => { assert.deepEqual(JSON.parse(received), createBody); response.setHeader('Content-Type', 'application/json'); response.end(managerResponse); });
  });
  for (const headers of [{ Origin: 'http://owner', 'x-tj-csrf': 'wrong' }, { Origin: 'http://wrong', 'x-tj-csrf': 'fixture-csrf' }]) assert.equal((await manage({ headers })).status, 403);
  assert.equal(writes, 0);
  const result = await manage(); assert.equal(result.status, 200); assert.equal(await result.text(), managerResponse); assert.equal(writes, 1);
}));

test('management refuses revoked sessions before dispatch, invalid body and oversize without writes', async () => fixture(async ({ server, socket }) => {
  managerSocket(socket); let writes = 0; server.on('request', () => { writes++; });
  for (const value of [{ ...createBody, invented_only: false }, { ...createBody, question: 'x'.repeat(2001) }, { revoke: 'foreign' }]) assert.equal((await manage({ body: JSON.stringify(value) })).status, 400);
  assert.equal((await manage({ body: 'x'.repeat(8193) })).status, 503);
  let checks = 0; global.fetch = async () => ++checks === 1 ? Response.json({ enabled: true, owner: true, csrf: 'fixture-csrf' }) : new Response('', { status: 401 });
  assert.equal((await manage()).status, 401); assert.equal(writes, 0);
}));

test('management uncertain response never retries and assistant/legacy cannot reach it', async () => fixture(async ({ server, socket }) => {
  managerSocket(socket); let writes = 0;
  server.on('request', request => { writes++; request.destroy(); });
  for (const value of ['assistant', 'private_legacy']) { profile.value = value; assert.equal((await manage()).status, 403); }
  assert.equal(writes, 0); profile.value = 'owner';
  const response = await manage(); assert.equal(response.status, 503); assert.match(await response.text(), /Reload saved questions/); assert.equal(writes, 1);
}));

const checkId = 'chk_0f8c2a8e-1d6b-4c3a-9e1f-2b7a5c4d3e21';
const checkList = JSON.stringify({ schema_version: 'check-owner-list-v1', checks: [], total: 0, limit: 50, read_at: '2026-10-11T12:00:00+00:00' });
const checkGrades = JSON.stringify({ schema_version: 'check-owner-grades-v1', days: 30, checks: 0, settled: 0, grade: { final_checks: 0 } });
const checkDetail = JSON.stringify({ schema_version: 'check-owner-detail-v1', check_id: checkId, answer: { verdict: 'wait' } });
function checkSocket(socket) {
  Object.assign(process.env, { TJ_ADVISOR_OWNER_ENABLED: 'false', TJ_CHECK_OWNER_ENABLED: 'true', TJ_CHECK_OWNER_SOCKET: socket, TJ_CHECK_OWNER_SOCKET_UID: String(process.getuid()) });
}

test('check BFF reads its own socket, fixed paths and exact check IDs only', async () => fixture(async ({ server, socket, calls }) => {
  checkSocket(socket); const seen = [];
  server.on('request', (request, response) => {
    seen.push(request.url); assert.equal(request.method, 'GET');
    for (const key of ['cookie', 'authorization', 'x-tj-gateway']) assert.equal(request.headers[key], undefined);
    response.setHeader('Content-Type', 'application/json'); response.end(request.url === '/owner/checks' ? checkList : request.url === '/owner/grades' ? checkGrades : checkDetail);
  });
  const owner = { headers: { cookie: 'invented-owner-session' } };
  const list = await loaded.exports.checkOwnerList(new Request('http://owner/api/check-owner/checks', owner));
  assert.equal(list.status, 200); assert.equal(await list.text(), checkList); assert.equal(calls(), 2);
  const detail = await loaded.exports.checkOwnerDetail(new Request(`http://owner/api/check-owner/checks/${checkId}`, owner), checkId);
  assert.equal(detail.status, 200); assert.equal(await detail.text(), checkDetail);
  const other = 'chk_11111111-1111-4111-8111-111111111111';
  assert.equal((await loaded.exports.checkOwnerDetail(new Request(`http://owner/api/check-owner/checks/${other}`, owner), other)).status, 503);
  for (const bad of ['../advisor', 'chk_x', `${checkId}/x`]) assert.equal((await loaded.exports.checkOwnerDetail(new Request('http://owner/x', owner), bad)).status, 404);
  assert.equal((await loaded.exports.checkOwnerList(new Request('http://owner/api/check-owner/checks?limit=500', owner))).status, 400);
  const grades = await loaded.exports.checkOwnerGrades(new Request('http://owner/api/check-owner/grades', owner));
  assert.equal(grades.status, 200); assert.equal(await grades.text(), checkGrades);
  assert.deepEqual(seen, ['/owner/checks', `/owner/checks/${checkId}`, `/owner/checks/${other}`, '/owner/grades']);
  profile.value = 'assistant'; assert.equal((await loaded.exports.checkOwnerList(new Request('http://owner/x', owner))).status, 403);
}));

test('private journal reads saved checks without an app session; advisor review stays owner-only', async () => fixture(async ({ server, socket, calls }) => {
  checkSocket(socket); profile.value = 'private_legacy'; const seen = [];
  server.on('request', () => seen.push('without-journal-setting'));
  const unset = await loaded.exports.checkOwnerList(new Request('http://journal/api/check-owner/checks'));
  assert.equal(unset.status, 503); assert.match(await unset.text(), /not switched on yet/); assert.deepEqual(seen, []);
  server.removeAllListeners('request'); process.env.TJ_CHECK_OWNER_JOURNAL = 'true';
  server.on('request', (request, response) => { seen.push(request.url); response.setHeader('Content-Type', 'application/json'); response.end(request.url === '/owner/checks' ? checkList : checkDetail); });
  const list = await loaded.exports.checkOwnerList(new Request('http://journal/api/check-owner/checks'));
  assert.equal(list.status, 200); assert.equal(await list.text(), checkList); assert.equal(calls(), 0);
  assert.equal((await loaded.exports.checkOwnerDetail(new Request(`http://journal/api/check-owner/checks/${checkId}`), checkId)).status, 200);
  assert.equal((await loaded.exports.checkOwnerList(new Request('http://journal/api/check-owner/checks', { method: 'POST', body: '{}' }))).status, 400);
  assert.equal((await read()).status, 503); assert.deepEqual(seen, ['/owner/checks', `/owner/checks/${checkId}`]);
  process.env.TJ_CHECK_OWNER_ENABLED = 'false';
  const off = await loaded.exports.checkOwnerList(new Request('http://journal/api/check-owner/checks'));
  assert.equal(off.status, 503); assert.match(await off.text(), /not switched on yet/); assert.equal(seen.length, 2);
}));

test('check BFF stays dormant until its own binding is enabled', async () => fixture(async ({ server }) => {
  let requests = 0; server.on('request', () => { requests += 1; });
  const response = await loaded.exports.checkOwnerList(new Request('http://owner/api/check-owner/checks'));
  assert.equal(response.status, 503); assert.match(await response.text(), /not switched on yet/); assert.equal(requests, 0);
}));
