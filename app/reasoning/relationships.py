from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..normalization import canonical_text


class RelationshipType(StrEnum):
    CORROBORATES = "CORROBORATES"
    CONTRADICTS = "CONTRADICTS"
    RECONCILES = "RECONCILES"
    UNRELATED = "UNRELATED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class RelationshipResult:
    relationship_type: RelationshipType
    confidence: float
    explanation: str
    factors: tuple[str, ...] = ()


def compare_facts(first: Any, second: Any) -> RelationshipResult:
    """Compare facts when deterministic fields are sufficient; otherwise stay ambiguous."""
    if canonical_text(first.subject) != canonical_text(second.subject):
        return _result(RelationshipType.UNRELATED, 0.98, "The facts refer to different subjects.", "subject differs")
    if canonical_text(first.predicate) != canonical_text(second.predicate):
        return _result(RelationshipType.UNRELATED, 0.95, "The facts describe different predicates.", "predicate differs")

    context_difference = _context_difference(first, second)
    if context_difference:
        return _result(
            RelationshipType.RECONCILES,
            0.93,
            f"The values differ because the facts have different {context_difference} context.",
            f"{context_difference} differs",
        )

    first_value = first.normalized_value if first.normalized_value is not None else first.value
    second_value = second.normalized_value if second.normalized_value is not None else second.value
    if first_value is None or second_value is None:
        return _result(
            RelationshipType.AMBIGUOUS,
            0.42,
            "The facts share a subject and predicate, but one or both values cannot be compared deterministically.",
            "value missing or unnormalized",
        )
    if first_value == second_value:
        return _result(
            RelationshipType.CORROBORATES,
            0.96,
            "The facts share the same subject, predicate, reporting context, and normalized value.",
            "context matches",
            "normalized values match",
        )
    return _result(
        RelationshipType.CONTRADICTS,
        0.91,
        f"The facts describe the same subject, predicate, and context but report different values: {first_value} versus {second_value}.",
        "context matches",
        "normalized values differ",
    )


def _context_difference(first: Any, second: Any) -> str | None:
    first_time = _time_key(first)
    second_time = _time_key(second)
    if first_time and second_time and first_time != second_time:
        return "time period"
    if first.scope and second.scope and canonical_text(first.scope) != canonical_text(second.scope):
        return "scope"
    if first.location and second.location and canonical_text(first.location) != canonical_text(second.location):
        return "geographic"
    return None


def _time_key(fact: Any) -> str:
    time = fact.time or {}
    return canonical_text(str(time.get("label") or time.get("year") or ""))


def _result(kind: RelationshipType, confidence: float, explanation: str, *factors: str) -> RelationshipResult:
    return RelationshipResult(kind, confidence, explanation, tuple(factors))