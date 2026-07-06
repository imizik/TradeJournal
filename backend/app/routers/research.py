"""Research workspace API.

Durable, editable state for research modules (currently the AI Buildout
cockpit). One JSON blob per ``slug`` with an optimistic-concurrency ``revision``:
clients send the ``base_revision`` they loaded and a stale save is rejected with
409 (carrying the current state) so concurrent tabs can't silently clobber.
"""

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.engine.research import get_or_create_workspace, save_workspace

router = APIRouter()


class WorkspaceResponse(BaseModel):
    slug: str
    revision: int
    schema_version: int
    data: dict[str, Any]
    updated_at: datetime | None = None


class WorkspaceSaveRequest(BaseModel):
    base_revision: int
    data: dict[str, Any]


def _to_response(row) -> WorkspaceResponse:
    return WorkspaceResponse(
        slug=row.slug,
        revision=row.revision,
        schema_version=row.schema_version,
        data=json.loads(row.data_json),
        updated_at=row.updated_at,
    )


@router.get("/workspaces/{slug}", response_model=WorkspaceResponse)
async def get_workspace(slug: str, session: Session = Depends(get_session)):
    row = get_or_create_workspace(session, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown research workspace: {slug}")
    return _to_response(row)


@router.put("/workspaces/{slug}", response_model=WorkspaceResponse)
async def save_workspace_route(
    slug: str,
    body: WorkspaceSaveRequest,
    session: Session = Depends(get_session),
):
    row = get_or_create_workspace(session, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown research workspace: {slug}")

    if body.base_revision != row.revision:
        # Stale write — return the current state so the client can reconcile.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "revision_conflict",
                "current": _to_response(row).model_dump(mode="json"),
            },
        )

    row = save_workspace(session, row, body.data)
    return _to_response(row)
