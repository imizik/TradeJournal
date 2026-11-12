"""Owner lock sign-in. Every route answers 404 while the lock is off.

Who may call each route is decided before the handler by AccessMiddleware:
the session check, sign-in and sign-out are open to the frontend; ending every
session needs an owner session or a process on the server (the break-glass).
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.engine import owner_lock

router = APIRouter()


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: str = Field(min_length=1, max_length=owner_lock.MAX_PASSPHRASE)


def _require_on() -> str:
    current = owner_lock.mode()
    if current == "off":
        raise HTTPException(404, "Not Found")
    return current


def _private(body, status=200):
    return JSONResponse(body, status, headers={"Cache-Control": "no-store"})


@router.get("/session")
async def session(request: Request):
    current = _require_on()
    token = owner_lock.token_from(request)
    return _private({"mode": current, "signed_in": await run_in_threadpool(owner_lock.signed_in, token)})


@router.post("/sign-in")
async def sign_in(body: SignIn, request: Request):
    _require_on()
    try:
        token, max_age = await run_in_threadpool(owner_lock.sign_in, body.passphrase, owner_lock.source_hint(request))
    except owner_lock.SignInRefused as refused:
        return _private({"detail": refused.detail}, refused.status)
    return _private({"token": token, "max_age": max_age})


@router.post("/sign-out")
async def sign_out(request: Request):
    _require_on()
    await run_in_threadpool(owner_lock.sign_out, owner_lock.token_from(request))
    return _private({"signed_out": True})


@router.post("/sign-out-everywhere")
async def sign_out_everywhere():
    _require_on()
    return _private({"ended": await run_in_threadpool(owner_lock.sign_out_everywhere)})
