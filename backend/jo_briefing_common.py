"""Bounded personal-memory/briefing schemas; no database, provider or application imports."""
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
Operation = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")]
Symbol = Annotated[str, Field(pattern=r"^[A-Z]{1,6}(\.[A-Z])?$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemorySave(Strict):
    operation_id: Operation
    memory_id: UUID | None = None
    base_revision: int = Field(default=0, ge=0)
    kind: Literal["statement", "thesis", "preference", "lesson"]
    symbol: Symbol | None = None
    original_text: Text
    interpretation: Text | None = None
    source: Literal["owner_statement", "owner_import", "jo_proposal"]
    source_reference: Text | None = None
    status: Literal["proposed", "active", "retired"] = "proposed"
    owner_confirmed: bool = False

    @model_validator(mode="after")
    def explicit_acceptance(self):
        if self.status != "proposed" and not self.owner_confirmed:
            raise ValueError("Activating or retiring a memory requires owner confirmation")
        if (self.memory_id is None) != (self.base_revision == 0):
            raise ValueError("New memories use revision 0; updates require a memory ID and base revision")
        return self


class MemoryRedact(Strict):
    operation_id: Operation
    base_revision: int = Field(ge=1)


class Evidence(Strict):
    id: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")]
    kind: Literal["fact", "belief", "estimate"]
    text: Text
    source: Text
    observed_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime

    @model_validator(mode="after")
    def chronology(self):
        if self.observed_at is not None and self.observed_at > self.retrieved_at:
            raise ValueError("Observation cannot follow retrieval")
        return self


class PacketSave(Strict):
    operation_id: Operation
    day: date
    as_of: AwareDatetime
    scope: Text
    evidence: list[Evidence] = Field(max_length=80)
    gaps: list[Text] = Field(max_length=30)
    memory_revision_ids: list[UUID] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_evidence(self):
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique")
        if len(set(self.memory_revision_ids)) != len(self.memory_revision_ids):
            raise ValueError("Memory revision IDs must be unique")
        if any(e.retrieved_at > self.as_of for e in self.evidence):
            raise ValueError("Evidence retrieval cannot follow packet as_of")
        if not self.evidence and not self.gaps:
            raise ValueError("An empty packet must explain its missing evidence")
        return self


class BriefingItem(Strict):
    symbol: Symbol | None = None
    what_matters: Text
    why_personal: Text
    what_changed: Text
    contrary_evidence: Text
    watch_out: Text
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class BriefingSave(Strict):
    operation_id: Operation
    packet_id: UUID
    author: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    prompt_version: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    model_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    summary: Text
    summary_evidence_ids: list[str] = Field(max_length=10)
    items: list[BriefingItem] = Field(max_length=3)
    limitations: list[Text] = Field(max_length=20)
    supersedes_id: UUID | None = None

