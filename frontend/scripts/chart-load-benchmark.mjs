/** Run ONLY against the isolated UX sandbox, with a production frontend build.
 * node scripts/chart-load-benchmark.mjs URL single|multi OUTPUT.json [timeoutSeconds] [5m|1h]
 * Uses real candle/history endpoints; settings are browser-local fixtures.
 */
import { chromium } from '@playwright/test';
import { writeFileSync } from 'node:fs';
const [url, layout, output, seconds = '1200', mainInterval = '5m'] = process.argv.slice(2);
if (!url || !['single', 'multi'].includes(layout) || !output || !['5m', '1h'].includes(mainInterval) || new URL(url).hostname !== '127.0.0.1') throw Error('Expected localhost sandbox URL, single|multi, output path');
const health = await fetch(`${url}/api/backend/health`).then(r => r.json());
if (!JSON.stringify(health).includes('ux_sandbox.db')) throw Error('Refusing a non-sandbox database');
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const settings = {symbol:'SPY', layout, intervals:mainInterval==='5m'?['5m','15m','1h','1D','1m']:['1h','15m','5m','1D','1m'], session:'extended', watchlist:['SPY'], newsHidden:true};
await context.addInitScript(settings => {
  localStorage.setItem('tj:chart-performance', '1');
  localStorage.setItem('tradejournal.charts.v1', JSON.stringify(settings));
  localStorage.setItem('tradejournal.charts.symbol-info.tab.v1', 'You');
}, settings);
await context.route('**/api/backend/charts/settings', route => route.fulfill({json:{revision:1,data:settings,updated_at:null}}));
// Keep live tick traffic out of the initial-load comparison; identical in all cells.
await context.route('**/api/backend/charts/stream?**', route => route.abort());
await context.route(/\/api\/backend\/charts\/(workspace|history)\?/, route => {
  const target = new URL(route.request().url()); target.searchParams.set('timing','true');
  return route.continue({url:target.toString()});
});
const page = await context.newPage();
const requests = [], errors = [], pending = new Set();
page.on('pageerror', e => errors.push(e.message));
page.on('response', response => {
  const target = new URL(response.url());
  if (!/\/charts\/(workspace|history)$/.test(target.pathname)) return;
  const work = (async () => {
    const body = await response.json();
    requests.push({path:target.pathname, interval:target.searchParams.get('interval'), status:response.status(),
      receivedMs: await page.evaluate(() => performance.now()), timing:await response.headerValue('server-timing'),
      request:response.request().timing(), bars:body.bars?.length, warmup:body.warmup, issue:body.issue ?? null,
      continuation:!!body.continuation});
  })().catch(e => errors.push(String(e)));
  pending.add(work); work.finally(() => pending.delete(work));
});
const started = new Date().toISOString();
await page.goto(`${url}/charts`, {waitUntil:'domcontentloaded'});
let samples = {}, completed = false;
const deadline = Date.now() + Number(seconds)*1000;
let nextReport = Date.now();
while (Date.now() < deadline) {
  samples = await page.evaluate(() => window.__tjChartPerformance?.samples ?? {});
  const candles = samples.initial_panel_candles ?? [], studies = samples.initial_panel_studies ?? [];
  if (Date.now() >= nextReport) {
    console.log(JSON.stringify({elapsed:Math.round((Date.now()-Date.parse(started))/1000),candles:candles.length,history:(samples.initial_panel_history ?? []).length,studies:studies.length,requests:requests.length,last:requests.at(-1)?.issue}));
    nextReport = Date.now()+30000;
  }
  if (studies.length === (layout==='single'?1:5)) { completed=true; break; }
  await page.waitForTimeout(250);
}
await Promise.all([...pending]);
await page.screenshot({path:output.replace(/\.json$/,'.png')});
const result={started,layout,settings,completed,errors,samples,requests};
writeFileSync(output, JSON.stringify(result,null,2));
console.log(JSON.stringify({output,completed,firstCandles:samples.initial_panel_candles,studies:samples.initial_panel_studies}));
await browser.close();
