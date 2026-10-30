"""Research job phone pings (docs/copilot-lab.md § Research queue): materiality, every gate, caps, dedupe, ntfy failure.
Stubbed job runs and a stubbed ntfy.publish only."""
import asyncio
import uuid
from dataclasses import replace

import jsonschema
import pytest
from sqlmodel import Session

from app.ai import research_job
from app.database import engine
from app.engine import copilot_investigations as inv
from app.engine import ntfy
from app.engine import research_queue as q
from app.models import CopilotInvestigation
from tests.test_research_queue import CFG, clean  # noqa: F401  (the shared table-cleaning fixture)

ON = replace(CFG, notify_enabled=True, notify_daily_max=3)


def _assessment(material=True, reason="Bernstein downgrade adds a financing risk the thesis ignored"):
    return {"summary": "Financing stress, not demand.", "key_findings": [], "counterpoints": [], "would_change_view": [],
            "citations": [{"url": "https://www.reuters.com/a", "publisher": "Reuters", "published_at": "2026-10-23T14:00:00Z",
                           "title": "Downgrade"}],
            "evidence_refs": [], "material_change": material, "material_reason": reason if material else ""}


def _run(assessment=None, checks=None):
    async def run(question, symbols, evidence, *, now, title, lim):
        saved = inv.save_research_result(title=title, symbol=(symbols or [None])[0], findings={"summary": "new"})
        return {"status": "ok", "metrics": {"cost_usd": 0.05}, "saved_id": saved["id"], "assessment": assessment or _assessment(),
                "checks": checks or {"unseen_citations": [], "unread_evidence_refs": [], "after_evidence_time": []}}
    return run


@pytest.fixture(autouse=True)
def wide_policy_budget(monkeypatch):
    """The research sender's own caps are under test here, on the real clock; the policy's research budget and pre-open
    allowance are tested in test_notification_policy."""
    monkeypatch.setenv("PING_BUDGET_RESEARCH", "20")
    monkeypatch.setenv("PING_PREOPEN_ALLOWANCE", "20")


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    def publish(title, message, *, priority=4, tags=("bell",), path="", direct_click=False):
        sent.append({"title": title, "message": message, "path": path, "direct_click": direct_click})
        return f"msg-{len(sent)}"

    monkeypatch.setattr(ntfy, "publish", publish)
    return sent


def _open(symbol="NBIS", title="NBIS recovery thesis"):
    return inv.save_research_result(title=title, symbol=symbol, findings={"summary": "s"})["id"]


def _job(cfg=ON, run=None, linked=None, question="Why is NBIS lagging?", symbols=("NBIS",)):
    q.enqueue_question(question, list(symbols), from_investigation=linked)
    return asyncio.run(q.QueueRunner(cfg, run_job=run or _run(), evidence_factory=lambda: "evidence").run_once())


# --------------------------------------------------------------------------- the schema and the prompt

def test_material_fields_are_required_bounded_and_conservative():
    schema = research_job.ASSESSMENT_SCHEMA
    assert {"material_change", "material_reason"} <= set(schema["required"])
    jsonschema.validate(_assessment(), schema)
    for bad in ({**_assessment(), "material_reason": "x" * 141}, {k: v for k, v in _assessment().items() if k != "material_change"},
                {**_assessment(), "material_change": "yes"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
    assert "material_change is false by default" in research_job.SYSTEM_PROMPT
    assert "Routine confirmation" in research_job.SYSTEM_PROMPT


# --------------------------------------------------------------------------- one ping, and every gate

def test_a_material_result_on_an_open_investigation_sends_one_ping(pushes):
    linked = _open()
    job = _job(linked=linked)
    assert job["status"] == "done" and job["notify"]["status"] == "sent" and job["notify"]["message_id"] == "msg-1"
    assert pushes == [{"title": "Research: NBIS – Bernstein downgrade adds a financing risk the thesis ignored",
                       "message": "Financing stress, not demand.", "path": f"/copilot-lab?investigation={linked}",
                       "direct_click": True}]
    # Once per job: deciding again sends nothing.
    assert q.plan_notification(job["id"], {"assessment": _assessment()}, ON) is None and len(pushes) == 1


@pytest.mark.parametrize("cfg,assessment,checks,reason", [
    (CFG, None, None, "notifications are off"),
    (ON, _assessment(material=False), None, "not material"),
    (ON, None, {"unseen_citations": ["https://invented.example/a"], "after_evidence_time": []}, "server checks not clean"),
    (ON, None, {"unseen_citations": [], "after_evidence_time": ["https://later.example/b"]}, "server checks not clean"),
    (ON, None, {"unseen_citations": [], "unread_evidence_refs": ["get_quotes"], "after_evidence_time": []}, "server checks not clean"),
    (ON, {**_assessment(), "citations": []}, None, "no citation"),
    (ON, {**_assessment(), "material_reason": " \x00\u202e "}, None, "no reason"),
])
def test_gates_skip_and_record_why(pushes, cfg, assessment, checks, reason):
    job = _job(cfg=cfg, run=_run(assessment, checks), linked=_open())
    assert job["status"] == "done" and job["notify"]["status"] == "skipped" and job["notify"]["reason"] == reason
    assert pushes == []


def test_only_linked_open_investigations_can_ping(pushes):
    unlinked = _job()
    assert unlinked["notify"]["reason"] == "not linked to an open investigation"
    closed = _open(title="Closed thesis")
    with Session(engine) as db:
        row = db.get(CopilotInvestigation, uuid.UUID(closed))
        row.status = "closed"
        db.add(row)
        db.commit()
    assert _job(linked=closed, question="Still?")["notify"]["reason"] == "not linked to an open investigation"
    assert pushes == []


def test_a_reassessment_links_through_its_investigation(pushes):
    linked = _open(symbol="CRWV", title="CRWV financing")
    q.enqueue("reassess", {"investigation_id": linked}, f"reassess:{linked}:x")
    job = asyncio.run(q.QueueRunner(ON, run_job=_run(), evidence_factory=lambda: "evidence").run_once())
    assert job["notify"]["status"] == "sent" and pushes[0]["title"].startswith("Research: CRWV – ")
    assert pushes[0]["path"] == f"/copilot-lab?investigation={linked}"


def test_one_ping_per_investigation_per_day_and_a_daily_cap(pushes, monkeypatch):
    first = _open()
    assert _job(linked=first, question="a")["notify"]["status"] == "sent"
    assert _job(linked=first, question="b")["notify"]["reason"] == "already pinged for this investigation today"
    capped = replace(ON, notify_daily_max=2)
    assert _job(cfg=capped, linked=_open(title="second"), question="c")["notify"]["status"] == "sent"
    assert _job(cfg=capped, linked=_open(title="third"), question="d")["notify"]["reason"] == "daily ping limit reached"
    assert len(pushes) == 2
    monkeypatch.setattr(q, "_today", lambda: "2099-01-01")  # a new ET day
    assert _job(linked=first, question="e")["notify"]["status"] == "sent" and len(pushes) == 3


def test_a_failed_ping_is_recorded_never_retried_and_never_fails_the_job(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise ntfy.NtfyError("ntfy refused the notification (429).")

    monkeypatch.setattr(ntfy, "publish", refuse)
    job = _job(linked=_open())
    assert job["status"] == "done" and job["notify"]["status"] == "failed" and "429" in job["notify"]["error"]
    assert len(calls) == 1 and q.plan_notification(job["id"], {"assessment": _assessment()}, ON) is None


def test_settings_default_off_and_tolerant(monkeypatch):
    assert q.settings().notify_enabled is False and q.settings().notify_daily_max == 3
    monkeypatch.setenv("RESEARCH_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_NOTIFY_DAILY_MAX", "lots")
    assert q.settings().notify_enabled is True and q.settings().notify_daily_max == 3


def test_a_failed_ping_still_counts_toward_the_day(monkeypatch):
    """ntfy may have delivered a push whose reply timed out: that investigation gets no second ping that day."""
    def timeout(*args, **kwargs):
        raise ntfy.NtfyError("ntfy could not be reached (ReadTimeout).")

    monkeypatch.setattr(ntfy, "publish", timeout)
    linked = _open()
    assert _job(linked=linked, question="a")["notify"]["status"] == "failed"
    sent = []
    monkeypatch.setattr(ntfy, "publish", lambda *a, **k: sent.append(a) or "id")
    assert _job(linked=linked, question="b")["notify"]["reason"] == "already pinged for this investigation today"
    capped = replace(ON, notify_daily_max=1)
    assert _job(cfg=capped, linked=_open(title="other"), question="c")["notify"]["reason"] == "daily ping limit reached"
    assert sent == []


def test_the_title_carries_no_control_or_bidi_characters_and_the_link_is_the_records_id(pushes):
    linked = _open()
    reason = "New\x00 financing\n risk\u202e\u2066 flagged\x1b[31m"
    job = _job(run=_run({**_assessment(), "material_reason": reason}), linked=linked.upper())  # the input as typed, not normalized
    assert job["notify"]["status"] == "sent" and job["notify"]["investigation_id"] == linked
    [push] = pushes
    assert push["title"] == "Research: NBIS – New financing risk flagged [31m"
    assert not any(ch in push["title"] for ch in "\x00\n\x1b\u202e\u2066")
    assert push["path"] == f"/copilot-lab?investigation={linked}"
