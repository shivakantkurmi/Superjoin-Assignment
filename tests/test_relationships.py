from decimal import Decimal

from app.models import Fact
from app.reasoning.relationships import RelationshipType, compare_facts


def fact(fact_id: str, value: str, period: str = "FY2024", scope: str = "company") -> Fact:
    return Fact(
        id=fact_id,
        subject="ABC Ltd",
        predicate="revenue",
        value=value,
        normalized_value=Decimal(value),
        time={"label": period},
        scope=scope,
    )


def test_equal_normalized_values_corroborate():
    result = compare_facts(fact("a", "125000000"), fact("b", "125000000"))
    assert result.relationship_type == RelationshipType.CORROBORATES


def test_same_context_different_values_contradict():
    result = compare_facts(fact("a", "500"), fact("b", "650"))
    assert result.relationship_type == RelationshipType.CONTRADICTS
    assert "different values" in result.explanation


def test_different_periods_reconcile_instead_of_contradicting():
    result = compare_facts(fact("a", "100", "FY2024"), fact("b", "20", "Q1 FY2024"))
    assert result.relationship_type == RelationshipType.RECONCILES
    assert "time period" in result.explanation


def test_different_subjects_are_unrelated():
    first = fact("a", "100")
    second = fact("b", "100")
    second.subject = "Other Ltd"
    result = compare_facts(first, second)
    assert result.relationship_type == RelationshipType.UNRELATED