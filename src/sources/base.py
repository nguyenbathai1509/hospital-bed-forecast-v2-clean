from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class SourceBatch:
    """Source-neutral payload returned by any V2 source adapter."""

    rows: list[dict]
    data_version: str
    source_refs: list[str] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class SourceReadiness:
    ready: bool
    business_date: date | None
    reason: str
    details: dict = field(
        default_factory=dict
    )


class SourceAdapter(Protocol):
    source_mode: str

    @property
    def source_ref(self) -> str:
        ...

    def check_readiness(
        self,
    ) -> SourceReadiness:
        ...

    def extract(
        self,
    ) -> SourceBatch:
        ...