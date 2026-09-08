from app.llm.fact_extractor import FactExtractor
from app.llm.gemini_client import GeminiClient
from app.models import Page


def test_fact_extractor_verifies_evidence_and_preserves_fact_fields():
    response = {
        "facts": [
            {
                "subject": "ABC Ltd",
                "predicate": "revenue",
                "object_value": "INR 125 crore",
                "fact_type": "revenue",
                "original_value": "INR 125 crore",
                "normalized_value": None,
                "unit": "crore",
                "currency": "INR",
                "time": {"label": "FY2024"},
                "scope": "company",
                "location": None,
                "qualifiers": {},
                "confidence": 0.94,
                "ambiguous": False,
                "evidence": {"quote": "Revenue for FY2024 was INR 125 crore.", "page": 1},
            }
        ]
    }
    client = GeminiClient(generate=lambda prompt, schema: response)
    facts, failures = FactExtractor(client).extract_page(
        Page("doc-1", 1, "Revenue for FY2024 was INR 125 crore.")
    )

    assert not failures
    assert facts[0].status == "VALID"
    assert facts[0].evidence.char_start == 0
    assert facts[0].confidence == 0.94


def test_fact_extractor_surfaces_ungrounded_evidence():
    response = {
        "facts": [
            {
                "subject": "ABC Ltd",
                "predicate": "revenue",
                "object_value": "INR 999 crore",
                "fact_type": "revenue",
                "original_value": "INR 999 crore",
                "confidence": 0.3,
                "evidence": {"quote": "Revenue was INR 999 crore.", "page": 1},
            }
        ]
    }
    client = GeminiClient(generate=lambda prompt, schema: response)
    facts, failures = FactExtractor(client).extract_page(
        Page("doc-1", 1, "Revenue for FY2024 was INR 125 crore.")
    )

    assert facts[0].status == "EVIDENCE_FAILED"
    assert failures[0].stage == "evidence_verification"