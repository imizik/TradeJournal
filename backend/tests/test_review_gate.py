"""Execute the actual GitHub guard with planted API results, no network."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/review_gate.cjs"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs Node")
BASE = "a" * 40
HEAD = "b" * 40


def gate(receipt=None, *, comments=None, base=BASE, event="schedule"):
    fixture = {
        "pr": {"number": 1, "state": "open", "head": {"sha": HEAD}, "base": {"sha": base},
               "labels": [{"name": "review-loop"}], "html_url": "https://github.com/owner/repo/pull/1"},
        "statuses": [receipt] if receipt else [], "comments": comments or [], "event": event,
    }
    program = """
const gate = require(process.argv[1]);
const f = JSON.parse(process.argv[2]);
const updates=[], notifications=[];
const github={rest:{pulls:{get:async()=>({data:f.pr}),list:()=>{}},
repos:{listCommitStatusesForRef:()=>{},createCommitStatus:async x=>updates.push(x)},
issues:{listComments:()=>{},createComment:async x=>notifications.push(x)}},
paginate:async(fn)=>fn===github.rest.pulls.list?[f.pr]:fn===github.rest.issues.listComments?f.comments:f.statuses};
gate({github,context:{repo:{owner:'owner',repo:'repo'},eventName:f.event,payload:f.event==='pull_request_target'?{pull_request:{number:1}}:{}},
core:{info:()=>{}},now:3600000}).then(()=>console.log(JSON.stringify({updates,notifications})));
"""
    p = subprocess.run(["node", "-e", program, str(SCRIPT), json.dumps(fixture)], capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def receipt(**kwargs):
    return {"context": "tradejournal/review-receipt", "state": "success",
            "description": f"clean base:{BASE} owner:codex pass:1", "creator": {"login": "owner"},
            "created_at": "1970-01-01T00:55:00Z", **kwargs}


def test_clean_exact_head_and_base_passes():
    assert gate(receipt(), event="pull_request_target")["updates"][0]["state"] == "success"


@pytest.mark.parametrize("item,base", [
    (None, BASE), (receipt(creator={"login": "outsider"}), BASE),
    (receipt(description="looks fine"), BASE), (receipt(), "c" * 40),
    (receipt(description=f"clean base:{BASE} owner:codex pass:4"), BASE),
])
def test_missing_forged_malformed_or_stale_receipts_never_pass(item, base):
    assert gate(item, base=base)["updates"][0]["state"] != "success"


def test_overdue_review_is_error_and_notifies_once_per_head():
    pending = receipt(state="pending", created_at="1970-01-01T00:00:00Z")
    result = gate(pending)
    assert result["updates"][0]["state"] == "error"
    assert len(result["notifications"]) == 1
    comment = {"user": {"login": "github-actions[bot]"}, "body": result["notifications"][0]["body"]}
    assert gate(pending, comments=[comment])["notifications"] == []


def test_explicit_review_error_notifies_without_waiting():
    result = gate(receipt(state="error"))
    assert result["updates"][0]["state"] == "error"
    assert result["notifications"]


def test_success_does_not_expire_while_head_and_base_stay_same():
    assert gate(receipt(created_at="1970-01-01T00:00:00Z"))["updates"][0]["state"] == "success"
