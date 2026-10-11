import { test, expect } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
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
async function startSidecar(script?: string) {
  child=spawn(executable, script ? [script] : ["scripts/research_studio_server.py","--cache-root",path.join(root,"sip"),"--store-root",path.join(root,"store"),"--port",String(port)],{cwd:backend,env:{...process.env,TJ_RESEARCH_TOKEN:token},stdio:"pipe"});
  let failure="";child.stderr?.on("data",b=>{failure=(failure+String(b)).slice(-16000);});
  await expect.poll(async()=>{if(child.exitCode!==null)throw new Error(failure);try{return(await fetch(origin+"/config",{headers:{authorization:"Bearer "+token}})).status;}catch{return 0;}},{timeout:15000}).toBe(200);
}
async function stopSidecar(signal: "SIGTERM" | "SIGKILL" = "SIGTERM") {
  if(child && child.exitCode===null){const exit=new Promise<void>(resolve=>child.once("exit",()=>resolve()));child.kill(signal);await exit;}
}
test.beforeAll(async()=>{
  root=path.join(mkdtempSync(path.join(os.tmpdir(),"tj-research-browser-")),"fixture");
  execFileSync(executable,["scripts/seed_research_studio_fixture.py",root],{cwd:backend});
  await startSidecar();
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
  const feedback:number[]=[], loading:number[]=[];
  for(let i=1;i<=20;i++) {
    await page.evaluate(() => {
      const target = document.querySelector('[aria-label="Conditions"] [role="status"]')!;
      const input = document.querySelector<HTMLInputElement>('input[aria-label="Condition 2 minimum"]')!;
      const state = window as unknown as {r3Feedback: Promise<{feedback:number;loading:number}>};
      state.r3Feedback = new Promise(resolve => {
        let start: number | null = null, ack: number | null = null;
        input.addEventListener("input", () => { start = performance.now(); }, {once:true,capture:true});
        const observer = new MutationObserver(() => {
          if (start === null) return;
          if (target.textContent?.includes("Preparing population") && ack === null) ack=performance.now()-start;
          if (ack !== null && target.textContent?.startsWith("Preview:")) {
            observer.disconnect(); resolve({feedback:performance.now()-start,loading:ack});
          }
        });
        observer.observe(target,{childList:true,characterData:true,subtree:true});
      });
    });
    await page.getByLabel("Condition 2 minimum",{exact:true}).fill(String(1.50+i*.002));
    const measured=await page.evaluate(()=>(window as unknown as {r3Feedback:Promise<{feedback:number;loading:number}>}).r3Feedback);
    feedback.push(measured.feedback);loading.push(measured.loading);
  }
  const p95=[...feedback].sort((a,b)=>a-b)[18];
  console.log("R3 fixture DOM feedback ms",JSON.stringify({feedback,loading,p95}));
  expect(p95).toBeLessThanOrEqual(250);expect(Math.max(...loading)).toBeLessThanOrEqual(250);
});

test("late previous-run chart is rejected when a changed draft starts another run",async({page})=>{
  await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();
  await page.getByRole("button",{name:"Reveal analysis (records exposure)"}).click();await expect(page.getByTestId("analysis-count")).toBeVisible();
  await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.84");await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeEnabled();
  let release:()=>void=()=>{}, entered:()=>void=()=>{};const gate=new Promise<void>(r=>release=r), started=new Promise<void>(r=>entered=r);let held=true;
  await page.route("**/research-studio/command",async route=>{if(held && route.request().postDataJSON().action==="chart"){held=false;const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});}else await route.continue();});
  await page.locator("button[data-occurrence-id]").first().click();await started;
  await page.getByRole("button",{name:"Run analysis",exact:true}).click();release();
  await expect(page.getByTestId("selected-id")).toHaveCount(0);
  await expect(page.getByLabel("Occurrence inspector")).toContainText("Select a candle");
  await expect(page.getByLabel("Chart explorer").locator("svg")).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeEnabled();
});

test("sidecar crash with surviving child refuses early recovery then retries exact run",async({page})=>{
  test.setTimeout(60000);
  expect((await cmd("runs")).runs.filter((r:{status:string})=>r.status==="queued")).toHaveLength(0);
  await stopSidecar();
  const pausedWorker=path.join(root,"paused-worker.py"), pausedSidecar=path.join(root,"paused-sidecar.py"), ready=path.join(root,"child-ready"), exited=path.join(root,"child-exited");
  const worker=path.join(backend,"scripts/research_studio_worker.py");
  writeFileSync(pausedWorker,`import importlib.util, os, signal\nfrom pathlib import Path\nspec=importlib.util.spec_from_file_location("actual_worker",${JSON.stringify(worker)})\nmodule=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\noriginal=module.analyze\ndef paused(*args,**kwargs):\n    Path(${JSON.stringify(ready)}).write_text(str(os.getpid()))\n    os.kill(os.getpid(),signal.SIGSTOP)\n    return original(*args,**kwargs)\nmodule.analyze=paused\ntry:\n    module.main()\nfinally:\n    Path(${JSON.stringify(exited)}).write_text("exited")\n`);
  writeFileSync(pausedSidecar,`import sys,os\nfrom pathlib import Path\nsys.path.insert(0,${JSON.stringify(backend)})\nfrom app.engine import research_studio_store as module\nfrom app.engine.research_studio_data import DiscoveryCache\nfrom app.engine.research_studio_session import ResearchSession\nfrom scripts.research_studio_server import create_app\nimport uvicorn\noriginal=module.subprocess.Popen\ndef launch(command,**kwargs):\n    command[1]=${JSON.stringify(pausedWorker)}\n    return original(command,**kwargs)\nmodule.subprocess.Popen=launch\nsource=DiscoveryCache(Path(${JSON.stringify(path.join(root,"sip"))}))\nsession=ResearchSession(source,module.ResearchStore(Path(${JSON.stringify(path.join(root,"store"))}),source_root=source.root))\nuvicorn.run(create_app(session,os.environ["TJ_RESEARCH_TOKEN"]),host="127.0.0.1",port=${port})\n`);
  let ownedPid:number|null=null;
  try {
    await startSidecar(pausedSidecar);await page.goto("/research-studio");await expect(page.getByRole("status").filter({hasText:"Preview:"})).toBeVisible();
    await page.getByLabel("Condition 2 minimum",{exact:true}).fill("1.83");await expect(page.getByRole("button",{name:"Run analysis",exact:true})).toBeEnabled();
    await page.getByRole("button",{name:"Run analysis",exact:true}).click();
    await expect.poll(()=>{try{return readFileSync(ready,"utf8");}catch{return "";}}).not.toBe("");ownedPid=Number(readFileSync(ready,"utf8"));
    await expect(page.getByLabel("Run status")).toContainText("running");
    const runId=(await cmd("runs")).runs[0].run_id;
    await stopSidecar("SIGKILL");await startSidecar();
    const before=await cmd("runs");expect(before.runs.filter((r:{status:string})=>r.status==="queued")).toHaveLength(0);
    await page.reload();await expect(page.getByRole("button",{name:new RegExp(runId)})).toBeVisible();await page.getByRole("button",{name:new RegExp(runId)}).click();
    await page.getByRole("button",{name:"Check worker / recover interrupted run"}).click();
    await expect(page.getByRole("alert",{name:"Research error"})).toContainText("already active");
    expect((await cmd("status",{run_id:runId})).status).toBe("running");
    process.kill(ownedPid,"SIGCONT");
    await expect.poll(()=>{try{return readFileSync(exited,"utf8");}catch{return "";}}).toBe("exited");ownedPid=null;
    await page.getByRole("button",{name:"Check worker / recover interrupted run"}).click();
    await expect(page.getByRole("button",{name:"Retry frozen run"})).toBeVisible();await expect(page.getByLabel("Run status")).toContainText("interrupted worker");
    await page.getByRole("button",{name:"Retry frozen run"}).click();await expect(page.getByRole("button",{name:"Reveal analysis (records exposure)"})).toBeVisible();
    const final=await cmd("status",{run_id:runId});expect(final.attempt).toBe(2);expect(final.status).toBe("completed");expect(final.exposures).toBe(0);
  } finally { if(ownedPid!==null){try{process.kill(ownedPid,"SIGCONT");process.kill(ownedPid,"SIGTERM");}catch{}} }
});
