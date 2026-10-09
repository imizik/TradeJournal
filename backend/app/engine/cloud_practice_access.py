"""Independent bearer identity for allowlisted sample reads/opt-in choices."""
import asyncio
from functools import lru_cache
import json
import os
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session

from app.engine import access
from app.models import AccessPrincipal
from cloud_mcp_d0 import SCOPE, reject_model_credentials
from cloud_mcp_d1_common import PRACTICE_SCOPE, SampleReadVerifier
from cloud_mcp_d2_common import WRITE_SCOPE


def require_sample(request):
    if (not all(os.environ.get(name) == "true" for name in
            ("TJ_ACCESS_ENABLED", "TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_CLOUD_MCP_ENABLED"))
            or getattr(request.app.state, "cloud_mcp_sample_only", False) is not True):
        raise HTTPException(503, "Sample connector is unavailable")
    try:
        reject_model_credentials()
    except ValueError:
        raise HTTPException(503, "Sample connector is unavailable") from None


@lru_cache(maxsize=1)
def verifier(path):
    if not path or not Path(path).is_absolute():
        raise ValueError("Configure the sample reader explicitly")
    return SampleReadVerifier(Path(path))


def initialize():
    """Pin the approved binding before the isolated API accepts any requests."""
    if os.environ.get("TJ_CLOUD_MCP_ENABLED") == "true":
        reject_model_credentials()
        verifier(os.environ.get("TJ_CLOUD_MCP_CONFIG", ""))


def require_choice_write(request):
    require_sample(request)
    if not all(os.environ.get(name) == "true" for name in
            ("TJ_SAMPLE_DECISION_WRITES", "TJ_CLOUD_MCP_DECISION_WRITES")):
        raise HTTPException(503, "Sample choice writes are unavailable")
    check = verifier(os.environ.get("TJ_CLOUD_MCP_CONFIG", ""))
    config = check.active_config()
    if config is None or config.decision_writes is not True:
        raise HTTPException(503, "Sample choice writes are unavailable")
    who = getattr(request.state, "access", None)
    if (who is None or who.owner or who.service or who.grants.get("decision_write") is not True
            or WRITE_SCOPE not in getattr(request.state, "cloud_mcp_scopes", ())):
        raise HTTPException(403, "Sample choice write permission required")


def identify(request, *, write=False):
    require_sample(request)
    if (len(request.headers.getlist("authorization")) != 1
            or any(request.headers.get(name) for name in ("cookie", "x-tj-gateway", "x-tj-service", "x-tj-bootstrap"))):
        raise HTTPException(401, "Sample reader authentication required")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(401, "Sample reader authentication required")
    try:
        check = verifier(os.environ.get("TJ_CLOUD_MCP_CONFIG", ""))
        verified = asyncio.run(check.verify_token(token))
    except (OSError, ValueError):
        verified = None
    required = {SCOPE, PRACTICE_SCOPE, WRITE_SCOPE} if write else {SCOPE, PRACTICE_SCOPE}
    if verified is None or not required <= set(verified.scopes):
        raise HTTPException(401, "Sample reader authentication required")
    config = check.active_config()
    if config is None:
        raise HTTPException(401, "Sample reader authentication required")
    linked = next(p for p in config.profiles if p.subject == verified.subject)
    if not linked.enabled:
        raise HTTPException(401, "Sample reader authentication required")
    with access._LOCK, Session(access.engine) as db:
        access._serialized(db)
        row = db.get(AccessPrincipal, linked.principal_id)
        if (row is None or row.id == access.OWNER or not row.enabled or row.version != linked.principal_version
                or row.credential_expires_at is None or row.credential_expires_at <= access.now()):
            raise HTTPException(401, "Sample reader authentication required")
        try:
            grants = json.loads(row.grants_json)
            # This first slice cannot turn an OAuth link into journal/live access.
            if (not isinstance(grants, dict) or grants.get("journal_read") is not False
                    or not isinstance(grants.get("run_ids"), list) or len(grants["run_ids"]) != 1
                    or not isinstance(grants.get("symbols"), list)
                    or not 1 <= len(grants["symbols"]) <= 2 or not set(grants["symbols"]) <= {"MU", "NBIS"}):
                raise ValueError()
            import uuid
            if str(uuid.UUID(grants["run_ids"][0])) != grants["run_ids"][0]:
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(403, "Sample reader grant is unavailable") from None
        access.consume_request_budget(db, row.id)
        db.commit()
        identity = access.Identity(row.id, "assistant", grants=grants)
        request.state.cloud_mcp_scopes = frozenset(verified.scopes)
        request.state.access = identity
        if write:
            require_choice_write(request)
        return identity
