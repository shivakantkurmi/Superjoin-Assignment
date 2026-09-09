from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .llm.relationship_reasoner import RelationshipReasoner
from .models import Fact, Page
from .normalization import canonical_text, normalize_fact
from .extraction.chunking import chunk_pages
from .reasoning.relationships import RelationshipResult, RelationshipType, compare_facts
from .retrieval.embeddings import VectorIndex, fact_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionFailure:
    """Record of a fact or evidence extraction failure in a specific page/stage."""
    message: str
    page_number: int
    stage: str = "fact_extraction"


@dataclass(frozen=True)
class ProcessingResult:
    facts: list[Fact]
    relationships: list[tuple[str, str, RelationshipResult]]
    failures: list[ExtractionFailure]


class ProcessingPipeline:
    """Run one document through extraction, normalization, retrieval, and comparison."""

    def __init__(self, extractor: Any, vector_index: VectorIndex, reasoner: RelationshipReasoner | None = None) -> None:
        self.extractor = extractor
        self.vector_index = vector_index
        self.reasoner = reasoner
        self.facts_by_id: dict[str, Fact] = {}

    def process(self, pages: list[Page]) -> ProcessingResult:
        logger.info("pipeline stage=started pages=%d", len(pages))
        document_facts: list[Fact] = []
        failures: list[ExtractionFailure] = []
        chunks = chunk_pages(pages)
        logger.info("pipeline stage=chunking chunks=%d status=completed", len(chunks))
        for chunk in chunks:
            logger.info("pipeline stage=local_candidate_extraction page=%d/%d status=started", chunk.page_number, len(pages))
            chunk_page = Page(chunk.document_id, chunk.page_number, chunk.text)
            facts, page_failures = self.extractor.extract_page(chunk_page)
            logger.info("pipeline stage=local_candidate_extraction page=%d/%d facts=%d failures=%d", chunk.page_number, len(pages), len(facts), len(page_failures))
            failures.extend(page_failures)
            for fact in facts:
                if fact.evidence:
                    fact.evidence = fact.evidence.__class__(
                        document_id=fact.evidence.document_id,
                        page_number=fact.evidence.page_number,
                        quote=fact.evidence.quote,
                        chunk_id=chunk.id,
                        char_start=fact.evidence.char_start,
                        char_end=fact.evidence.char_end,
                    )
            document_facts.extend(normalize_fact(fact) for fact in facts)

        relationships: list[tuple[str, str, RelationshipResult]] = []
        candidate_ids_by_fact: dict[str, set[str]] = {}
        candidates_by_fact = self.vector_index.search_similar_batch(document_facts)
        for fact, candidates in zip(document_facts, candidates_by_fact):
            candidate_ids_by_fact[fact.id] = {candidate_id for candidate_id, _score in candidates}

        # Ensure matching facts are compared even when embedding similarity is below the shortlist threshold.
        for fact in document_facts:
            fact_key = (canonical_text(fact.subject), canonical_text(fact.predicate))
            candidate_ids_by_fact[fact.id].update(
                candidate.id
                for candidate in self.facts_by_id.values()
                if candidate.evidence
                and candidate.evidence.document_id != fact.evidence.document_id
                and canonical_text(candidate.predicate) == fact_key[1]
                and _same_subject(candidate.subject, fact.subject)
            )

        for fact in document_facts:
            for candidate_id in candidate_ids_by_fact[fact.id]:
                candidate = self.facts_by_id.get(candidate_id)
                if candidate is None:
                    continue
                result = compare_facts(candidate, fact)
                if result.relationship_type == RelationshipType.AMBIGUOUS and self.reasoner is not None:
                    logger.info("pipeline stage=gemini_relationship candidate=%s status=started", candidate.id)
                    result = self.reasoner.reason(candidate, fact, (candidate.evidence, fact.evidence))
                if result.relationship_type.value != "UNRELATED":
                    relationships.append((candidate.id, fact.id, result))

        logger.info("pipeline stage=vector_index facts=%d status=started", len(document_facts))
        self.vector_index.add_facts(document_facts)
        self.facts_by_id.update({fact.id: fact for fact in document_facts})
        logger.info("pipeline stage=completed facts=%d relationships=%d failures=%d", len(document_facts), len(relationships), len(failures))
        return ProcessingResult(document_facts, relationships, failures)

    def remove_document(self, document_id: str) -> None:
        """Remove a document's facts from both retrieval and comparison state."""
        self.facts_by_id = {
            fact_id: fact
            for fact_id, fact in self.facts_by_id.items()
            if not fact.evidence or fact.evidence.document_id != document_id
        }
        self.vector_index.rebuild(self.facts_by_id.values())


def _same_subject(first: str, second: str) -> bool:
    first_words = set(canonical_text(first).split())
    second_words = set(canonical_text(second).split())
    return bool(first_words and second_words) and (first_words <= second_words or second_words <= first_words)


def fact_to_dict(fact: Fact) -> dict[str, Any]:
    evidence = None
    if fact.evidence:
        evidence = {
            "document_id": fact.evidence.document_id,
            "page_number": fact.evidence.page_number,
            "quote": fact.evidence.quote,
            "chunk_id": fact.evidence.chunk_id,
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