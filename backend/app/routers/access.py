"""App login is separate from Gmail OAuth and exists only in authenticated mode."""
from datetime import timedelta
import json
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.database import get_session
from app.engine import access
from app.models import AccessAudit, AccessPrincipal, AccessSession

router = APIRouter()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    identifier: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=128)


class Grant(Strict):
    symbols: list[str] = Field(min_length=1, max_length=10)
    run_ids: list[str] = Field(default_factory=list, max_length=30)
    journal_read: bool = False


class Assistant(Strict):
    identifier: str = Field(min_length=3, max_length=64)
    grants: Grant


class Reset(Strict):
    grants: Grant


@router.get("/challenge")
def challenge(request: Request, response: Response, db: Session = Depends(get_session)):
    audience = access.gateway(request)
    token = secrets.token_urlsafe(32)
    row = AccessSession(digest=access.digest(token), principal_id=None, audience=audience,
        csrf=secrets.token_urlsafe(32), expires_at=access.now() + timedelta(minutes=10))
    # A browser gets one challenge cookie; keep persistent challenge rows bounded too.
    access.prune(db)
    challenge_ids = select(AccessSession.digest).where(AccessSession.principal_id.is_(None)).order_by(AccessSession.created_at.desc()).offset(199)
    from sqlalchemy import delete
    db.exec(delete(AccessSession).where(AccessSession.digest.in_(challenge_ids)))
    db.add(row)
    db.commit()
    access.set_cookie(response, token, kind="challenge", max_age=600)
    return {"csrf": row.csrf}


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    token = access.login(request, body.identifier, body.key)
    access.set_cookie(response, token)
    response.delete_cookie(access.cookie_name("challenge"), path="/", secure=access.secure(), httponly=True, samesite="lax")
    return {"signed_in": True}


@router.post("/bootstrap")
def bootstrap(request: Request, response: Response):
    token = access.bootstrap(request)
    access.set_cookie(response, token, max_age=43200)
    return {"signed_in": True}


@router.get("/me")
def me(request: Request):
    who = request.state.access
    if who.service:
        raise HTTPException(403, "Browser session required")
    return {"enabled": True, "identifier": who.identifier, "owner": who.owner,
        "grants": who.grants, "csrf": who.csrf, "sample_data": os.environ.get("TJ_ACCESS_SAMPLE_DATA") == "true"}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_session)):
    access._serialized(db)
    row = db.get(AccessSession, request.state.access.session_digest)
    if row:
        db.delete(row)
        db.commit()
    response.delete_cookie(access.cookie_name(), path="/", secure=access.secure(), httponly=True, samesite="lax")
    return {"signed_out": True}


@router.get("/assistants")
def assistants(db: Session = Depends(get_session)):
    return [access.assistant_row(row) for row in db.exec(select(AccessPrincipal).where(AccessPrincipal.id != access.OWNER)).all()]


@router.post("/assistants", status_code=201)
def create(body: Assistant, db: Session = Depends(get_session)):
    access._serialized(db)
    key = access.create_assistant(db, body.identifier, body.grants.model_dump())
    return {"identifier": body.identifier, "key": key, "shown_once": True}


@router.post("/assistants/{identifier}/reset")
def reset(identifier: str, body: Reset, db: Session = Depends(get_session)):
    access.grant_valid(body.grants.model_dump())
    access._serialized(db)
    row = db.get(AccessPrincipal, identifier)
    if not row or row.id == access.OWNER:
        raise HTTPException(404, "Assistant not found")
    row.version += 1
    row.enabled = True
    row.grants_json = json.dumps(body.grants.model_dump())
    row.credential_expires_at = access.now() + timedelta(days=30)
    key = secrets.token_urlsafe(32)
    row.key_hash = access.HASHER.hash(key)
    db.add(row)
    access.audit(db, access.OWNER, "assistant_reset", "accepted", identifier)
    db.commit()
    return {"identifier": identifier, "key": key, "shown_once": True}


@router.post("/assistants/{identifier}/revoke")
def revoke(identifier: str, body: Strict, db: Session = Depends(get_session)):
    access._serialized(db)
    row = db.get(AccessPrincipal, identifier)
    if not row or row.id == access.OWNER:
        raise HTTPException(404, "Assistant not found")
    row.enabled = False
    row.version += 1
    db.add(row)
    access.audit(db, access.OWNER, "assistant_revoke", "accepted", identifier)
    db.commit()
    return {"revoked": True}


@router.get("/audit")
def audit(db: Session = Depends(get_session)):
    return db.exec(select(AccessAudit).order_by(AccessAudit.created_at.desc()).limit(100)).all()
