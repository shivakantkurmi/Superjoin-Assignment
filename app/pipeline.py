from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm.fact_extractor import ExtractionFailure, FactExtractor
from .models import Fact, Page
from .normalization import normalize_fact
from .reasoning.relationships import RelationshipResult, compare_facts
from .retrieval.embeddings import VectorIndex, fact_text


@dataclass(frozen=True)
class ProcessingResult:
    facts: list[Fact]
    relationships: list[tuple[str, str, RelationshipResult]]
    failures: list[ExtractionFailure]


class ProcessingPipeline:
    """Run one document through extraction, normalization, retrieval, and comparison."""

    def __init__(self, extractor: FactExtractor, vector_index: VectorIndex) -> None:
        self.extractor = extractor
        self.vector_index = vector_index
        self.facts_by_id: dict[str, Fact] = {}

    def process(self, pages: list[Page]) -> ProcessingResult:
        document_facts: list[Fact] = []
        failures: list[ExtractionFailure] = []
        for page in pages:
            facts, page_failures = self.extractor.extract_page(page)
            failures.extend(page_failures)
            document_facts.extend(normalize_fact(fact) for fact in facts)

        relationships: list[tuple[str, str, RelationshipResult]] = []
        for fact in document_facts:
            for candidate_id, _score in self.vector_index.search_similar(fact):
                candidate = self.facts_by_id[candidate_id]
                result = compare_facts(candidate, fact)
                if result.relationship_type.value != "UNRELATED":
                    relationships.append((candidate.id, fact.id, result))

        self.vector_index.add_facts(document_facts)
        self.facts_by_id.update({fact.id: fact for fact in document_facts})
        return ProcessingResult(document_facts, relationships, failures)


def fact_to_dict(fact: Fact) -> dict[str, Any]:
    evidence = None
    if fact.evidence:
        evidence = {
            "document_id": fact.evidence.document_id,
            "page_number": fact.evidence.page_number,
            "quote": fact.evidence.quote,
            "char_start": fact.evidence.char_start,
            "char_end": fact.evidence.char_end,
        }
    return {
        "id": fact.id,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object": fact.object,
        "fact_type": fact.fact_type,
        "value": fact.value,
        "normalized_value": str(fact.normalized_value) if fact.normalized_value is not None else None,
        "unit": fact.unit,
        "time": fact.time,
        "scope": fact.scope,
        "location": fact.location,
        "qualifiers": fact.qualifiers,
        "confidence": fact.confidence,
        "status": fact.status,
        "evidence": evidence,
    }