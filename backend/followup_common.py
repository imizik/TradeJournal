"""Personal follow-up records shared by Check and the existing app worker."""

from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from market_watch_common import parse_time, verify
from conditional_plan_common import read_json

Text = Annotated[str, Field(min_length=1, max_length=1000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FollowupSave(Strict):
    operation_id: Annotated[str, Field(min_length=1, max_length=160)]
    title: Annotated[str, Field(min_length=1, max_length=100)]
    original_request: Text
    why_it_matters: Text
    review_question: Text
    symbols: Annotated[list[str], Field(max_length=3)] = []
    next_review_at: str
    expires_at: str
    linked_plan_id: str | None = None

    @field_validator("symbols")
    @classmethod
    def symbols_valid(cls, value):
        import re

        result = list(dict.fromkeys(s.upper() for s in value))
        if any(not re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", s) for s in result):
            raise ValueError("Invalid ticker")
        return result


class WebEvidence(Strict):
    url: Annotated[str, Field(max_length=1000)]
    finding: Text
    observed_at: str

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        u = urlsplit(value)
        if u.scheme != "https" or not u.hostname or u.username or u.password:
            raise ValueError("Require a public HTTPS source without credentials")
        return value


class FollowupReview(Strict):
    input_id: str
    outcome: Literal["unchanged", "update", "resolved", "blocked"]
    summary: Annotated[str, Field(min_length=1, max_length=700)]
    what_changed: Text
    why_it_matters: Text
    next_step: Text
    evidence_refs: Annotated[list[str], Field(max_length=10)] = []
    web_sources: Annotated[list[WebEvidence], Field(max_length=5)] = []
    notify: bool = False
    next_review_at: str | None = None


def validate_record(record):
    verify(record)
    if record["format"] != "jo-followup-v1" or record["kind"] not in (
        "request",
        "review",
        "cancel",
    ):
        raise ValueError("Invalid follow-up record")
    from stock_watch_common import identifier

    identifier(record["followup_id"], "fup")
    identifier(record["record_id"], "fur")
    if not record["actor"]:
        raise ValueError("Missing owner")
    created = parse_time(record["created_at"])
    if record["kind"] == "request":
        request = FollowupSave.model_validate(record["body"])
        due, expires = (
            parse_time(request.next_review_at),
            parse_time(request.expires_at),
        )
        if not created <= due < expires <= created + timedelta(days=7):
            raise ValueError("Review must be before expiry, within seven days")
    elif record["kind"] == "review":
        FollowupReview.model_validate(record["body"])
    return record


def project(records, now):
    request = next(r for r in records if r["kind"] == "request")
    reviews = [r for r in records if r["kind"] == "review"]
    latest = reviews[-1] if reviews else None
    state = "active"
    if any(r["kind"] == "cancel" for r in records):
        state = "cancelled"
    elif latest and latest["body"]["outcome"] == "resolved":
        state = "resolved"
    elif now >= parse_time(request["body"]["expires_at"]):
        state = "expired"
    notified = [r for r in reviews if r["body"]["notify"]]
    return {
        "request": request,
        "latest_review": latest,
        "last_notification_intent": notified[-1] if notified else None,
        "state": state,
        "next_review_at": latest["body"]["next_review_at"]
        if latest
        else request["body"]["next_review_at"],
        "parent_id": latest["record_id"] if latest else request["record_id"],
    }


def ready(directory, now):
    from pathlib import Path

    value = read_json(Path(directory) / "followup-readiness.json")
    verify(value)
    if (
        value.get("format") != "jo-followup-readiness-v1"
        or value.get("enabled") is not True
    ):
        raise ValueError("Personal follow-ups are not enabled")
    if not 0 <= (now - parse_time(value["created_at"])).total_seconds() <= 90:
        raise ValueError("Personal follow-up worker heartbeat is stale")
    return value


def export(directory, record):
    from stock_watch_common import write_once

    validate_record(record)
    write_once(directory, f"followup-{record['record_id']}.json", record)


def read_work(directory, followup_id, now):
    from pathlib import Path
    from stock_watch_common import identifier

    identifier(followup_id, "fup")
    ready(directory, now)
    result = read_json(Path(directory) / f"followup-work-{followup_id}.json")
    verify(result)
    if (
        result.get("format") != "jo-followup-work-v1"
        or result.get("followup_id") != followup_id
    ):
        raise ValueError("Follow-up work mismatch")
    if not 0 <= (now - parse_time(result["created_at"])).total_seconds() <= 90:
        raise ValueError("Follow-up work is stale")
    return result
