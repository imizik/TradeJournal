"""Bounded input for the opt-in sample choice increment; no caller identity."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WRITE_SCOPE = "practice:write"
CHOICE_GET_PATH = "GET /cloud-mcp/practice/opportunities/{opportunity_id}/choice"
WRITE_PATHS = frozenset({"POST /cloud-mcp/practice/opportunities/{opportunity_id}/choice"})
MAX_CHOICE_BYTES = 16384


class PracticeChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["take", "wait", "skip"]
    rationale: str = Field(min_length=1, max_length=2000)
    wait_condition: str | None = Field(default=None, max_length=500)
    wait_expiry: str | None = Field(default=None, max_length=64)
    plan: dict | None = None
