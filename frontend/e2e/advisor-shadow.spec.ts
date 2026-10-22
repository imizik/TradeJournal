import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const BACKEND = path.resolve(__dirname, "../../backend");
const VENV_PYTHON = path.join(BACKEND, ".venv/bin/python");
const PYTHON = existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3";
const DB = path.join(BACKEND, "data/e2e_seed.db");
const API = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || 8099}`;
const env = { ...process.env, DATABASE_URL: `sqlite:///${DB}`, MIGRATION_DATABASE_URL: `sqlite:///${DB}`, PRACTICE_AGENT_ENABLED: "false" };

for (const transport of ["manual-paste", "oauth-mcp"]) {
test(`${transport} advisor/shadow packet, assistance, complete choices and paired review survive reopening`, async ({ page, request }) => {
  const seeded = execFileSync(PYTHON, ["-c", `
import json
from sqlmodel import Session
from app.database import engine
from app.engine import advisor_shadow
with Session(engine) as db:
    run, assignment, token = advisor_shadow.create_fixture(db)
    print(json.dumps({"run_id":str(run),"assignment_id":str(assignment),"token":token}))
`], { cwd: BACKEND, env, encoding: "utf8" });
  const fixture = JSON.parse(seeded) as { run_id: string; assignment_id: string; token: string };
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/?practice_run=${fixture.run_id}`);
    const panel = page.getByTestId("advisor-shadow-panel");
    await expect(panel).toContainText("INDEPENDENCE UNVERIFIED");
    await expect(panel).toContainText("No backend inference runs");
    await panel.getByText("Exact neutral packet", { exact: true }).click();
    await expect(panel.getByTestId("advisor-packet")).toContainText("simulated_raw");
    await panel.getByLabel("Your question").fill("Is a SPY close above 100 sufficient to take this plan?");
    await panel.getByLabel("Your plan").fill("I would wait for a completed 15-minute close above 100, with a fixed stop and guard.");
    const competing = await page.context().newPage();
    await competing.goto(`/?practice_run=${fixture.run_id}`);
    const competingPanel = competing.getByTestId("advisor-shadow-panel");
    await competingPanel.getByLabel("Your question").fill("A different invented question");
    await competingPanel.getByLabel("Your plan").fill("A different invented plan");
    await panel.getByRole("button", { name: "Save and expose advisor packet" }).click();
    await expect(panel).toContainText("Comparison: assisted");
    const exported = JSON.parse(await panel.getByLabel("Advisor packet for copying").inputValue());
    await competingPanel.getByRole("button", { name: "Save and expose advisor packet" }).click();
    await expect(competingPanel).toContainText("A different immutable advisor request is already saved");
    await expect(competingPanel.getByLabel("Your question")).toHaveValue(exported.question);
    await expect(competingPanel.getByLabel("Your plan")).toHaveValue(exported.user_plan);
    expect(JSON.parse(await competingPanel.getByLabel("Advisor packet for copying").inputValue())).toEqual(exported);
    await competing.close();
    const opportunity = exported.packet.opportunities[0];
    const answer = {
      summary: "No verified TAKE is supported; wait for an approved market packet.",
      interpretation: "An invented close above 100 is an illustration, not evidence of a real breakout.",
      risks: "Market calendar, real prices and valid risk levels are unavailable.",
      conditions: "Require verified raw facts, calendar, strict 15m trigger, fixed stop/target and guard.",
      gaps: "Real provider data, news and full-session coverage are unavailable.",
      references: [{ opportunity_id: opportunity.opportunity_id, fact_name: opportunity.price_facts[0].name }],
    };
    const envelope = {
      version: exported.version, assignment_id: exported.assignment_id, run_id: exported.run_id,
      packet_sha256: exported.packet_sha256, request_sha256: exported.request_sha256, answer,
    };
    expect(exported.assignment_id).toBe(fixture.assignment_id);
    expect(exported.run_id).toBe(fixture.run_id);
    let savedReceipt;
    if (transport === "manual-paste") {
      // The real backend commits, then its response is lost. Recovery reads
      // the complete immutable receipt without an automatic retry.
      let imports = 0;
      await page.route(`**/advisor-shadow/runs/${fixture.run_id}/advisor-import`, async (route) => {
        imports += 1;
        const response = await route.fetch();
        expect(response.ok()).toBeTruthy();
        await route.abort("failed");
      });
      await panel.getByTestId("advisor-answer-form").getByRole("textbox").fill(JSON.stringify(envelope));
      await panel.getByRole("button", { name: "Save advisor response" }).click();
      await expect(panel).toContainText("Saved advisor receipt recovered from the owner record. No retry was sent.");
      expect(imports).toBe(1);
      savedReceipt = JSON.parse(await panel.getByTestId("advisor-receipt").textContent() ?? "{}");
      await page.unroute(`**/advisor-shadow/runs/${fixture.run_id}/advisor-import`);
    } else {
      // Generated offline OAuth token, real MCP SDK -> restricted backend ->
      // shared SQLite ledger. No issuer contact, external grant or listener.
      savedReceipt = JSON.parse(execFileSync(PYTHON, ["-c", `
import json,sys,tempfile,time,uuid
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlmodel import create_engine
import httpx
from cloud_mcp_advisor import create_server
from cloud_mcp_advisor_bridge import build_app
from tests.test_cloud_mcp_d0 import _token,_jwks,ISSUER,JWKS_URL
from app.engine import advisor_shadow
from sqlmodel import Session
body=json.load(sys.stdin)
engine=create_engine("sqlite:///"+sys.argv[1],connect_args={"check_same_thread":False,"timeout":2})
resource="https://advisor.example.test/advisor/mcp"
with Session(engine) as db:
    exported=advisor_shadow.owner_view(db,uuid.UUID(body["run_id"]))["advisor"]["export"]
with tempfile.TemporaryDirectory(prefix="tj-advisor-browser-") as temp:
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    keys=Path(temp)/"keys.json"
    keys.write_text(json.dumps({"issuer_url":ISSUER,"jwks_url":JWKS_URL,"fetched_at":int(time.time())-1,"expires_at":int(time.time())+600,**_jwks(key.public_key())}))
    cfg=Path(temp)/"advisor.json"
    cfg.write_text(json.dumps({"enabled":True,"advisor_only":True,"issuer_url":ISSUER,"resource_url":resource,"jwks_url":JWKS_URL,"jwks_file":str(keys),"client_id":"advisor-client","backend_socket":str(Path(temp)/"unused.sock"),"profiles":[{"subject":"jo-advisor","id":"advisor_"+str(uuid.uuid4()),"enabled":True,"binding_version":1,**{k:exported[k] for k in ("assignment_id","run_id","packet_sha256","request_sha256")}}]}))
    token=_token(key,audience=resource,subject="jo-advisor",client_id="advisor-client",scope="advisor:profile advisor:read advisor:write")
    server=create_server(cfg,backend_transport=httpx.ASGITransport(app=build_app(engine,cfg)))
    with TestClient(server.streamable_http_app()) as client:
        response=client.post(resource,headers={"Authorization":"Bearer "+token,"Accept":"application/json"},json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"save_advisor_answer","arguments":{k:body[k] for k in ("packet_sha256","request_sha256","answer")}}})
        result=response.json()["result"]
        assert not result.get("isError"),result
        print(json.dumps(result["structuredContent"]["receipt"]))
` , DB], { cwd: BACKEND, env: { PATH: process.env.PATH, NODE_ENV: "test", PYTHON_DOTENV_DISABLED: "1" }, input: JSON.stringify(envelope), encoding: "utf8" }));
      await panel.getByRole("button", { name: "Reload advisor record" }).click();
      await expect(panel).toContainText("oauth-mcp");
    }
    await expect(panel.getByTestId("advisor-saved-answer")).toContainText(answer.summary);
    expect(savedReceipt.transport).toBe(transport);
    expect(savedReceipt.submitted_output).toEqual(envelope);
    expect(savedReceipt.request_sha256).toBe(exported.request_sha256);
    expect(savedReceipt.packet_sha256).toBe(exported.packet_sha256);
    await expect(panel.getByTestId("advisor-saved-answer")).toContainText("sample_fixture");
    // The external interface's actor is server-derived; manual fixture transport is explicit.
    execFileSync(PYTHON, ["-c", `
import json,sys,uuid
from sqlmodel import Session
from app.database import engine
from app.engine import advisor_shadow
from app.models import PracticeAgentCall
data=json.load(sys.stdin)
with Session(engine) as db:
    call=db.get(PracticeAgentCall,uuid.UUID(data["assignment_id"]))
    packet=json.loads(call.payload_json)
    body={"assignment_id":str(call.id),"packet_sha256":advisor_shadow.digest(packet),"choices":[
        {"opportunity_id":o["opportunity_id"],"decision":"skip","rationale":"Shadow fixture: no verified setup"}
        for o in packet["opportunities"]]}
    advisor_shadow.submit(db,call.id,data["token"],body)
`], { cwd: BACKEND, env, input: JSON.stringify(fixture) });
    const run = (await (await request.get(`${API}/practice/runs/${fixture.run_id}`)).json());
    const first = run.opportunities[0];
    const human = await request.post(`${API}/practice/opportunities/${first.id}/choice`, { data: { decision: "wait", rationale: "Human fixture: waiting for verified evidence", wait_condition: "Approved real market packet", wait_expiry: new Date(Date.now() + 3600_000).toISOString() } });
    expect(human.ok()).toBeTruthy();
    await page.reload();
    await expect(page.getByTestId("advisor-saved-answer")).toContainText(answer.summary);
    expect(JSON.parse(await page.getByLabel("Advisor packet for copying").inputValue())).toEqual(exported);
    expect(JSON.parse(await page.getByTestId("advisor-receipt").textContent() ?? "{}")).toEqual(savedReceipt);
    await expect(panel.getByLabel("Your question")).toHaveValue(exported.question);
    await expect(panel.getByLabel("Your plan")).toHaveValue(exported.user_plan);
    const paired = page.getByTestId("practice-opportunity").filter({ hasText: `Opportunity ${first.id}` });
    await expect(paired).toContainText("Disagreement: you WAIT · agent SKIP");
    await expect(paired).toContainText("assisted");
    await expect(paired).toContainText("Your paper none");
    expect(run.agent.cost).toBeNull();
    expect(run.agent.usage).toBeNull();
    expect(run.agent.limits).toBeNull();
    const width = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth }));
    expect(width.page).toBeLessThanOrEqual(width.viewport + 1);
  } finally {
    execFileSync(PYTHON, ["-c", `
import sys,uuid
from sqlmodel import Session,select
from app.database import engine
from app.engine import practice
from app.models import DecisionContext,DecisionRecord,PracticeAgentCall,PracticeRun,JobRun
with Session(engine) as db:
    run=db.get(PracticeRun,uuid.UUID(sys.argv[1]))
    if run:
        opps=practice.opportunities(db,run.id)
        for opp in opps:
            for record in practice.records(db,opp).values(): db.delete(record)
        call=db.exec(select(PracticeAgentCall).where(PracticeAgentCall.run_id==run.id)).first()
        if call: db.delete(call)
        db.flush()
        for opp in opps:
            context=db.get(DecisionContext,opp.context_id)
            db.delete(opp)
            db.flush()
            db.delete(context)
        job=db.get(JobRun,run.job_id)
        db.delete(run)
        db.flush()
        db.delete(job)
        db.commit()
` , fixture.run_id], { cwd: BACKEND, env });
  }
});

}
