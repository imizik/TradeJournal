from fastapi import APIRouter

from app.environment import describe

router = APIRouter()


@router.get("/health")
def health():
    """
    Liveness, plus which database this process is talking to.

    The environment block exists so an operator or an agent can tell a Neon
    dev branch from production before pressing anything. It carries a redacted
    identity only -- never credentials.
    """
    return {"status": "ok", "environment": describe().as_dict()}
