import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.engine.gmail_poller import GmailPollingError, begin_gmail_oauth, finish_gmail_oauth

router = APIRouter()

FRONTEND_PUBLIC_URL = os.getenv("FRONTEND_PUBLIC_URL", "http://127.0.0.1:3000").rstrip("/")


@router.get("/gmail/start")
async def start_gmail_auth():
    try:
        return {"auth_url": begin_gmail_oauth()}
    except GmailPollingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/gmail/callback")
async def gmail_auth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        return RedirectResponse(f"{FRONTEND_PUBLIC_URL}/?gmail_auth=error")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing Gmail OAuth callback code or state")

    try:
        finish_gmail_oauth(code=code, state=state)
    except GmailPollingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return RedirectResponse(f"{FRONTEND_PUBLIC_URL}/?gmail_auth=success")
