import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";

const BACKEND = path.resolve(__dirname, "../../backend");
const PYTHON = path.join(BACKEND, ".venv/bin/python");
const DB = path.join(BACKEND, "data/e2e_seed.db");
const API = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || 8099}`;
const env = { ...process.env, DATABASE_URL: `sqlite:///${DB}`, MIGRATION_DATABASE_URL: `sqlite:///${DB}`, PRACTICE_AGENT_ENABLED: "false" };

test("manual advisor/shadow packet, assistance, complete choices and paired review survive reopening", async ({ page, request }) => {
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
    await panel.getByRole("button", { name: "Save and expose advisor packet" }).click();
    await expect(panel).toContainText("Comparison: assisted");
    const exported = JSON.parse(await panel.getByLabel("Advisor packet for copying").inputValue());
    const opportunity = exported.packet.opportunities[0];
    const answer = {
      summary: "No verified TAKE is supported; wait for an approved market packet.",
      interpretation: "An invented close above 100 is an illustration, not evidence of a real breakout.",
      risks: "Market calendar, real prices and valid risk levels are unavailable.",
      conditions: "Require verified raw facts, calendar, strict 15m trigger, fixed stop/target and guard.",
      gaps: "Real provider data, news and full-session coverage are unavailable.",
      references: [{ opportunity_id: opportunity.opportunity_id, fact_name: opportunity.price_facts[0].name }],
    };
    await panel.getByTestId("advisor-answer-form").getByRole("textbox").fill(JSON.stringify(answer));
    await panel.getByRole("button", { name: "Save advisor response" }).click();
    await expect(panel.getByTestId("advisor-saved-answer")).toContainText(answer.summary);
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
    const paired = page.getByTestId("practice-opportunity").filter({ hasText: `Opportunity ${first.id}` });
    await expect(paired).toContainText("Disagreement: human WAIT · agent SKIP");
    await expect(paired).toContainText("assisted");
    await expect(paired).toContainText("Human paper none");
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
