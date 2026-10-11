"""Manual loopback R3 research sidecar. No autostart or production provisioning."""
import argparse
from pathlib import Path
import os
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402
from app.engine.research_studio_data import DiscoveryCache  # noqa: E402
from app.engine.research_studio_store import ResearchStore  # noqa: E402
from app.engine.research_studio_session import Busy, ResearchSession  # noqa: E402

ACTIONS = frozenset({"preview", "enqueue", "runs", "status", "result", "cancel", "retry", "execute", "recover", "chart", "variant", "compare", "conclude", "notes", "describe"})


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    arguments: dict


def create_app(session, token):
    if len(token) < 32:
        raise ValueError("TJ_RESEARCH_TOKEN needs at least 32 characters")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    def authorize(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(403, "Research access refused")
    @app.get("/config", dependencies=[Depends(authorize)])
    def config():
        return session.config()
    @app.post("/command", dependencies=[Depends(authorize)])
    def command(body: Command):
        if body.action not in ACTIONS:
            raise HTTPException(400, "Unknown research action")
        try:
            methods = {"preview": session.preview, "enqueue": session.enqueue, "runs": session.runs,
                       "status": session.store.status, "result": session.store.result,
                       "execute": session.execute, "recover": session.store.recover, "chart": session.chart}
            methods.update(variant=session.variant, compare=session.compare,
                           conclude=session.variants.conclude, notes=session.variants.notes, describe=session.describe)
            if body.action in ("cancel", "retry"):
                return session.store.control(action=body.action, **body.arguments)
            return methods[body.action](**body.arguments)
        except Busy as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise HTTPException(400, "Research request refused: " + str(exc)[:300]) from exc
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args()
    token = os.environ.get("TJ_RESEARCH_TOKEN", "")
    source = DiscoveryCache(args.cache_root)
    session = ResearchSession(source, ResearchStore(args.store_root, source_root=source.root))
    import uvicorn
    uvicorn.run(create_app(session, token), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
