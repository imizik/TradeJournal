"""Bounded company-research submission schemas; no application or database imports."""
import re
from typing import Literal
from urllib.parse import urlsplit
from datetime import date
from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=500)
    publisher: str = Field(min_length=1, max_length=120)
    published_at: str | None = Field(default=None, max_length=40)
    excerpt: str = Field(min_length=1, max_length=1000)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
            raise ValueError("Ordinary public source URL required")
        if re.search(r"(?:token|secret|password|signature|api.?key|auth)=", parts.query, re.I):
            raise ValueError("Access-bearing URLs cannot be saved")
        return value


class NumericEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["actual", "estimate", "guidance"]
    metric: Literal["revenue", "eps", "gross_margin", "operating_margin", "cash", "debt", "operating_cash_flow", "capital_expenditure", "shares"]
    period_end: date
    basis: Literal["gaap", "adjusted", "ifrs", "unknown"]
    currency: str = Field(min_length=3, max_length=3)
    unit: str = Field(min_length=1, max_length=30)
    value: str | None = Field(default=None, max_length=48, strict=True)
    low: str | None = Field(default=None, max_length=48, strict=True)
    high: str | None = Field(default=None, max_length=48, strict=True)
    source_index: int = Field(ge=0, le=29)
    share_basis: str = Field(min_length=1, max_length=120)

    @field_validator("value", "low", "high")
    @classmethod
    def finite_decimal(cls, value):
        if value is None:
            return value
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("A finite decimal string is required") from None
        if not number.is_finite():
            raise ValueError("A finite decimal string is required")
        return value

    @model_validator(mode="after")
    def point_or_range(self):
        if self.value is not None and self.low is None and self.high is None:
            return self
        if self.value is None and self.low is not None and self.high is not None and Decimal(self.low) <= Decimal(self.high):
            return self
        raise ValueError("Supply one point value or a complete ordered range")


class FindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["fact", "interpretation", "question"]
    claim: str = Field(min_length=1, max_length=12000)
    sources: list[Citation] = Field(max_length=30)
    numbers: list[NumericEvidence] = Field(default_factory=list, max_length=20)

