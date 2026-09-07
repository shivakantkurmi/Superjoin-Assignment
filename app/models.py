from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Page:
    document_id: str
    page_number: int
    text: str
    is_scanned: bool = False


@dataclass(frozen=True)
class Evidence:
    document_id: str
    page_number: int
    quote: str
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class Fact:
    """Flexible fact shape; predicate and qualifiers support unknown fact types."""

    id: str
    subject: str
    predicate: str
    object: Any = None
    fact_type: str = "unknown"
    value: Any = None
    normalized_value: Any = None
    unit: str | None = None
    time: dict[str, str | None] = field(default_factory=dict)
    scope: str | None = None
    location: str | None = None
    qualifiers: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: Evidence | None = None
    status: str = "VALID"