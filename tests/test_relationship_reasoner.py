from app.llm.gemini_client import GeminiClient
from app.llm.relationship_reasoner import RelationshipReasoner
from app.models import Fact
from app.reasoning.relationships import RelationshipType


def make_fact(value: str) -> Fact:
    return Fact(
        id=value,
        subject="ABC Ltd",
        predicate="revenue",
        value=value,
        normalized_value=value,
        time={"label": "FY2024"},
        scope="company",
    )


def test_reasoner_accepts_structured_gemini_result():
    response = {
        "relationship_type": "RECONCILES",
        "confidence": 0.88,
        "explanation": "The reporting periods differ.",
        "factors": ["time period differs"],
    }
    reasoner = RelationshipReasoner(GeminiClient(generate=lambda prompt, schema: response))
    result = reasoner.reason(make_fact("100"), make_fact("20"))

    assert result.relationship_type == RelationshipType.RECONCILES
    assert result.confidence == 0.88


def test_reasoner_surfaces_invalid_gemini_result_as_ambiguous():
    response = {"relationship_type": "NOT_A_RELATIONSHIP", "confidence": 2}
    reasoner = RelationshipReasoner(GeminiClient(generate=lambda prompt, schema: response))
    result = reasoner.reason(make_fact("100"), make_fact("20"))

    assert result.relationship_type == RelationshipType.AMBIGUOUS
    assert result.confidence == 0.2