import base64
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.engine.gmail_poller import GmailPollingError, gmail_watch_state, register_gmail_watch
from app.routers.sync import queue_gmail_push_pipeline

router = APIRouter()


class GmailWatchRequest(BaseModel):
    topic_name: str | None = None
    label_ids: list[str] | None = None


def _verification_token() -> str:
    return os.getenv("GMAIL_PUBSUB_VERIFICATION_TOKEN", "").strip()


def _decode_pubsub_message(body: dict[str, Any]) -> dict[str, Any]:
    message = body.get("message")
    if not isinstance(message, dict):
        raise HTTPException(status_code=400, detail="Missing Pub/Sub message envelope")

    data = message.get("data")
    if not isinstance(data, str) or not data:
        return {}

    try:
        padded = data + "=" * (-len(data) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Pub/Sub message data: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub message payload")
    return payload


def _verify_push_token(token: str | None, authorization: str | None) -> None:
    expected = _verification_token()
    if not expected:
        return

    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    if token != expected and bearer != expected:
        raise HTTPException(status_code=401, detail="Invalid Gmail Pub/Sub verification token")


@router.get("/watch/status")
async def watch_status():
    return {"configured": bool(gmail_watch_state()), "state": gmail_watch_state()}


@router.post("/watch")
async def watch_gmail(body: GmailWatchRequest | None = None):
    try:
        state = register_gmail_watch(
            topic_name=body.topic_name if body else None,
            label_ids=body.label_ids if body else None,
        )
    except GmailPollingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "watch_registered", "state": state}


@router.post("/push")
async def gmail_pubsub_push(
    request: Request,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    _verify_push_token(token, authorization)

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub envelope")

    payload = _decode_pubsub_message(body)
    history_id = payload.get("historyId")
    email_address = payload.get("emailAddress")

    job, queued = queue_gmail_push_pipeline(
        session,
        history_id=str(history_id) if history_id is not None else None,
        email_address=str(email_address) if email_address is not None else None,
    )
    return {"accepted": True, "queued": queued, "run_id": str(job.id)}
