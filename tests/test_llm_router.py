from app.llm.providers import LLMRouter
from app.llm.relationship_reasoner import RelationshipReasoner
from app.models import Fact
from app.reasoning.relationships import RelationshipType


def test_router_uses_second_provider_after_first_fails():
    class Failing:
        def generate_json(self, prompt, schema):
            raise RuntimeError("temporary failure")

    class Working:
        def generate_json(self, prompt, schema):
            return {"relationship": "unresolved"}

    assert LLMRouter([Failing(), Working()]).generate_json("prompt", {}) == {"relationship": "unresolved"}


def test_router_reports_when_all_providers_fail():
    class Failing:
        def generate_json(self, prompt, schema):
            raise RuntimeError("down")

    try:
        LLMRouter([Failing(), Failing()]).generate_json("prompt", {})
    except Exception as exc:
        assert "All configured LLM providers failed" in str(exc)
    else:
        raise AssertionError("router should fail when all providers fail")


def test_reasoner_degrades_to_ambiguous_when_all_providers_fail():
    """When both Gemini and Groq fail, the reasoner must return AMBIGUOUS
    with low confidence instead of propagating the exception up to the
    pipeline (which would abort the entire PDF processing job).
    """
    class Failing:
        def generate_json(self, prompt, schema):
            raise RuntimeError("all providers down")

    reasoner = RelationshipReasoner(LLMRouter([Failing(), Failing()]))
    fact = Fact(
        id="f1",
        subject="ABC Ltd",
        predicate="revenue",
        value="125 crore",
        time={"label": "FY2024"},
    )
    result = reasoner.reason(fact, fact)
    assert result.relationship_type == RelationshipType.AMBIGUOUS
    assert result.confidence <= 0.3