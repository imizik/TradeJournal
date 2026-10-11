"""Owner-only forwarding to an explicitly started loopback research sidecar."""
import os
from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    arguments: dict


def forward(path, body=None):
    token = os.environ.get("TJ_RESEARCH_TOKEN", "")
    port = os.environ.get("TJ_RESEARCH_PORT", "8097")
    if len(token) < 32 or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise HTTPException(503, "Research Studio is not connected. Start the local research sidecar with approved roots.")
    try:
        with httpx.Client(timeout=65, trust_env=False, follow_redirects=False) as client:
            response = client.request("POST" if body else "GET", f"http://127.0.0.1:{int(port)}{path}",
                                      headers={"Authorization": "Bearer " + token}, json=body)
        if response.status_code != 200:
            raise HTTPException(response.status_code if response.status_code in (400, 409) else 503,
                                response.json().get("detail", "Research unavailable"))
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Research sidecar unavailable; inspect the local research process") from exc


@router.get("/config")
def config():
    return forward("/config")


@router.post("/command")
def command(body: Command):
    return forward("/command", body.model_dump())
