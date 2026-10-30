"""Append-only company observations, independent of journal and trading records."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ResearchCompany(SQLModel, table=True):
    __tablename__ = "company_research_company"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    symbol: str = Field(unique=True, index=True)
    name: str = ""
    cik: str | None = None
    followed: bool = True
    revision: int = 0
    thesis: str = ""
    assumptions_json: str = "[]"
    created_at: datetime = Field(default_factory=utc_now_naive)
    updated_at: datetime = Field(default_factory=utc_now_naive)


class ResearchSnapshot(SQLModel, table=True):
    __tablename__ = "company_research_snapshot"
    __table_args__ = (UniqueConstraint("company_id", "component", "operation_id"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(index=True)
    component: str
    operation_id: str
    provider: str
    state: str = "ready"
    observed_at: datetime = Field(default_factory=utc_now_naive)
    payload_json: str
    digest: str


class ResearchAssignment(SQLModel, table=True):
    __tablename__ = "company_research_assignment"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(index=True)
    question: str
    actor: str = "manual"
    context_json: str
    context_hash: str
    status: str = "queued"
    created_at: datetime = Field(default_factory=utc_now_naive)
    expires_at: datetime


class ResearchFinding(SQLModel, table=True):
    __tablename__ = "company_research_finding"
    __table_args__ = (UniqueConstraint("assignment_id", "operation_id"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(index=True)
    assignment_id: uuid.UUID
    operation_id: str
    actor: str
    payload_json: str
    digest: str
    disposition: str = "proposed"
    created_at: datetime = Field(default_factory=utc_now_naive)
