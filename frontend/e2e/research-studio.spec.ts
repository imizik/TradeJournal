import { test, expect } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const backend=path.resolve(__dirname,"../../backend"), python=path.join(backend,".venv/bin/python");
const executable=process.env.CI ? "python" : python;
const port=Number(process.env.E2E_RESEARCH_PORT || "19097"), token="research-browser-fixture-token-000000000000";
let child: ChildProcess, root: string;
const origin=`http://127.0.0.1:${port}`;
async function cmd(action:string,args:object={}) {
  const r=await fetch(origin+"/command",{method:"POST",headers:{"Content-Type":"application/json",authorization:"Bearer "+token},body:JSON.stringify({action,arguments:args})});
  const data=await r.json(); if(!r.ok)throw new Error(JSON.stringify(data)); return data;
}
test.beforeAll(async()=>{
  root=path.join(mkdtempSync(path.join(os.tmpdir(),"tj-research-browser-")),"fixture");
  execFileSync(executable,["scripts/seed_research_studio_fixture.py",root],{cwd:backend});
  child=spawn(executable,["scripts/research_studio_server.py","--cache-root",path.join(root,"sip"),"--store-root",path.join(root,"store"),"--port",String(port)],{cwd:backend,env:{...process.env,TJ_RESEARCH_TOKEN:token},stdio:"pipe"});
  let failure="";child.stderr?.on("data",b=>{failure+=String(b);});
  await expect.poll(async()=>{if(child.exitCode!==null)throw new Error(failure);try{return(await fetch(origin+"/config",{headers:{authorization:"Bearer "+token}})).status;}catch{return 0;}},{timeout:15000}).toBe(200);
});
test.afterAll(async()=>{if(child && child.exitCode===null){child.kill("SIGTERM");await new Promise<void>(resolve=>{child.once("exit",()=>resolve());setTimeout(()=>{child.kill("SIGKILL");resolve();},3000);});}});

test("question-start connects real preview, immutable run, views, exact bars and exposure reopen",async({page})=>{
  const leaked:string[]=[];page.on("request",r=>{if(/\/charts\/(history|stream)/.test(r.url()))leaked.push(r.url());});
  await page.goto("/research-studio");
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).toContainText("7 events");
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();
  await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Reveal analysis (records exposure)",exact:true}).click();
  await expect(page.getByTestId("analysis-count")).toContainText("N 7");
  const n=await page.getByTestId("analysis-count").textContent();
  const first=page.locator("button[data-occurrence-id]").first(), id=await first.getAttribute("data-occurrence-id");
  await first.click();await expect(page.getByTestId("selected-id")).toHaveText(id!);
  await expect(page.getByText("Completed prices through decision only",{exact:false})).toBeVisible();
  const chartCloses=await page.locator("[data-bar-close]").evaluateAll(nodes=>nodes.map(n=>n.getAttribute("data-bar-close")));
  expect(chartCloses.every(stamp=>Date.parse(stamp!)<=Date.parse(id!.slice(id!.indexOf(":")+1)))).toBeTruthy();
  await page.getByRole("button",{name:"Reveal future chart (records exposure)"}).click();
  await expect(page.getByText("Future revealed and recorded",{exact:false})).toBeVisible();
  await page.getByLabel("Chart zoom").selectOption("12");
  await expect(page.locator("[data-bar-close]")).toHaveCount(12);
  expect(readdirSync(path.join(root,"store")).filter(f=>f.startsWith("inspection.")).some(f=>JSON.parse(readFileSync(path.join(root,"store",f),"utf8")).future_revealed)).toBeTruthy();
  await page.getByRole("button",{name:/Distribution bin/}).filter({hasText:/[1-9]/}).first().click();
  await expect(page.getByTestId("analysis-count")).toHaveText(n!);
  await page.getByRole("button",{name:`Inspect ${id}`,exact:true}).click();
  await expect(page.getByTestId("selected-id")).toHaveText(id!);
  const saved=await cmd("runs"), runId=saved.runs[0].run_id, before=(await cmd("status",{run_id:runId})).exposures;
  await page.reload();await expect(page.getByRole("button",{name:new RegExp(runId)})).toBeVisible();
  await page.getByRole("button",{name:new RegExp(runId)}).click();
  await expect(page.getByTestId("analysis-count")).toContainText("N 7");
  expect((await cmd("status",{run_id:runId})).exposures).toBe(before+1);
  expect(leaked).toEqual([]);
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.locator("button[data-occurrence-id]").first().click();
  await expect(page.getByText("Completed prices through decision only",{exact:false})).toBeVisible();
  await page.screenshot({path:test.info().outputPath("studio-desktop.png"),fullPage:true});
});

test("chart-start conditions use decision features and edits label prior results immediately",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.getByRole("button",{name:"Inspect decision",exact:true}).click();
  await expect(page.getByRole("button",{name:"Use decision features as conditions"})).toBeVisible();
  const engineId=await page.locator("button[data-occurrence-id]").first().getAttribute("data-occurrence-id");
  await expect(page.getByTestId("selected-id")).toHaveText(engineId!);
  await page.getByRole("button",{name:"Use decision features as conditions"}).click();
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();
  await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();
  await page.getByRole("button",{name:"Reveal analysis (records exposure)"}).click();
  await expect(page.getByTestId("analysis-count")).toBeVisible();
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.6");
  await expect(page.getByText(/Previous result — draft changed/)).toBeVisible();
  await expect(page.getByText(/outcome-informed/)).toBeVisible();
});

test("late preview cannot replace newer threshold; invalid input disables Run",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  let release:()=>void=()=>{}, entered:()=>void=()=>{};
  const gate=new Promise<void>(r=>release=r), started=new Promise<void>(r=>entered=r);
  await page.route("**/research-studio/command",async route=>{
    const body=route.request().postDataJSON();
    if(body.action==="preview" && body.arguments.raw.predicates[1].minimum===123){entered();await gate;await route.fulfill({json:{event_count:999}}).catch(()=>{});}else await route.continue();
  });
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("123");await started;
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.7");
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).not.toContainText("999");
  await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeEnabled();release();
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).toContainText("events");
  await page.getByLabel("Window start").fill("601");
  await expect(page.getByRole("alert",{name:"Research error"})).toContainText("aligned");
  await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeDisabled();
});

test("queued cancellation and explicit retry preserve logical run and attempt history",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.8");await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeEnabled();
  let hold=true;await page.route("**/research-studio/command",async route=>{if(hold && route.request().postDataJSON().action==="execute")await route.fulfill({json:{status:"dispatched"}});else await route.continue();});
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();
  await expect(page.getByRole("button",{name:"Cancel run"})).toBeVisible();
  const began=Date.now();await page.getByRole("button",{name:"Cancel run"}).click();
  await expect(page.getByRole("button",{name:"Retry frozen run"})).toBeVisible();expect(Date.now()-began).toBeLessThan(1000);
  hold=false;await page.getByRole("button",{name:"Retry frozen run"}).click();
  await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();
  await expect(page.getByRole("region",{name:"Run status"})).toContainText("attempt 2");
});

test("research workspace fits a phone and source refusal is visible",async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto("/research-studio");
  await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.getByLabel("Chart date").fill("2024-10-01");await page.getByRole("button",{name:"Inspect decision",exact:true}).click();
  await expect(page.getByRole("alert",{name:"Research error"})).toContainText("discovery");
  await page.screenshot({path:test.info().outputPath("studio-phone.png"),fullPage:true});
});

test("delayed result and chart responses cannot replace newer run or selection",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();
  let release:()=>void=()=>{}, entered:()=>void=()=>{};const gate=new Promise<void>(r=>release=r), started=new Promise<void>(r=>entered=r);
  let hold=true;
  await page.route("**/research-studio/command",async route=>{
    if(hold && route.request().postDataJSON().action==="result") {hold=false;const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});}else await route.continue();
  });
  await page.getByRole("button",{name:"Reveal analysis (records exposure)"}).click();await started;
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.9");await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeEnabled();
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();release();
  await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();await expect(page.getByTestId("analysis-count")).toHaveCount(0);
  await page.getByRole("button",{name:"Reveal analysis (records exposure)"}).click();await expect(page.getByTestId("analysis-count")).toBeVisible();
  let releaseChart:()=>void=()=>{}, enteredChart:()=>void=()=>{};const chartGate=new Promise<void>(r=>releaseChart=r), chartStarted=new Promise<void>(r=>enteredChart=r);let chartHold=true;
  await page.route("**/research-studio/command",async route=>{
    if(chartHold && route.request().postDataJSON().action==="chart"){chartHold=false;const response=await route.fetch();enteredChart();await chartGate;await route.fulfill({response}).catch(()=>{});}else await route.fallback();
  });
  await page.locator("button[data-occurrence-id]").nth(0).click();await chartStarted;
  const newer=page.locator("button[data-occurrence-id]").nth(1), id=await newer.getAttribute("data-occurrence-id");await newer.click();
  await expect(page.getByText("Completed prices through decision only",{exact:false})).toBeVisible();releaseChart();
  await expect(page.getByTestId("selected-id")).toHaveText(id!);
});

test("warm edit feedback and loading meet bounded fixture budgets",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  const feedback:number[]=[];
  for(let i=0;i<20;i++) {
    const start=Date.now();await page.getByLabel("Condition 2 minimum",{exact:true}).fill(String(1.50+i*.002));
    await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();feedback.push(Date.now()-start);
  }
  const sorted=[...feedback].sort((a,b)=>a-b), p95=sorted[18];
  console.log("R3 fixture visible edit feedback ms",JSON.stringify({feedback,p95}));expect(p95).toBeLessThanOrEqual(250);
  const start=Date.now();await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.7");await expect(page.getByRole("status").filter({hasText:"Preparing population"})).toBeVisible();expect(Date.now()-start).toBeLessThanOrEqual(250);
});
