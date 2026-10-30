"""Jo research submissions: bounded schemas only; no database, provider or application imports."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from jo_briefing_common import NONBLANK, Operation, Strict, Symbol

KINDS = ("dossier", "audit", "narrative", "red_team")
CONTEXT_KINDS = ("dossier", "audit", "red_team")
BODY_CHARS = 12_000
Title = Annotated[str, Field(min_length=1, max_length=120, pattern=NONBLANK)]
Body = Annotated[str, Field(min_length=1, max_length=BODY_CHARS, pattern=NONBLANK)]
Publisher = Annotated[str, Field(min_length=1, max_length=120, pattern=NONBLANK)]
# A date or a time with its offset; a pattern rather than an exported format, so strict connectors accept both.
Published = Annotated[str, Field(min_length=10, max_length=40,
                                 pattern=r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2}))?$")]


class Source(Strict):
    url: Annotated[str, Field(min_length=8, max_length=500, pattern=r"^https?://[^\s]+$")]
    publisher: Publisher
    published_at: Published

    @field_validator("published_at")
    @classmethod
    def real_time(cls, value: str) -> str:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ResearchSave(Strict):
    operation_id: Operation
    kind: Literal["dossier", "audit", "narrative", "red_team"]
    symbols: list[Symbol] = Field(default_factory=list, max_length=10)
    title: Title
    body: Body
    sources: list[Source] = Field(default_factory=list, max_length=30)
    as_of: AwareDatetime
    request_id: UUID | None = None

    @model_validator(mode="after")
    def by_kind(self):
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("List each symbol once")
        if self.kind == "dossier" and not self.sources:
            raise ValueError("A dossier cites its sources")
        if self.kind == "dossier" and not self.symbols:
            raise ValueError("A dossier names the symbols it covers")
        if (self.kind == "red_team") != (self.request_id is not None):
            raise ValueError("request_id is required for red_team and refused for any other kind")
        return self
