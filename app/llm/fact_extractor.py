from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from ..ingestion import verify_evidence
from ..models import Evidence, Fact, Page
from .gemini_client import GeminiClient, GeminiResponseError


class ExtractedEvidence(BaseModel):
    quote: str = Field(min_length=1)
    page: int = Field(ge=1)


class ExtractedFact(BaseModel):
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_value: Any = None
    fact_type: str = Field(default="unknown", min_length=1)
    original_value: Any = None
    normalized_value: Any = None
    unit: str | None = None
    currency: str | None = None
    time: dict[str, str | None] = Field(default_factory=dict)
    scope: str | None = None
    location: str | None = None
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool = False
    evidence: ExtractedEvidence


class ExtractionPayload(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractionFailure:
    message: str
    page_number: int
    stage: str = "fact_extraction"


class FactExtractor:
    def __init__(self, client: GeminiClient) -> None:
        self.client = client

    def extract_page(self, page: Page) -> tuple[list[Fact], list[ExtractionFailure]]:
        prompt = self._prompt(page)
        try:
            data = self.client.generate_json(prompt, ExtractionPayload)
            payload = ExtractionPayload.model_validate(data)
        except (ValidationError, GeminiResponseError) as exc:
            return [], [ExtractionFailure(str(exc), page.page_number)]

        facts: list[Fact] = []
        failures: list[ExtractionFailure] = []
        for candidate in payload.facts:
            grounded, start, end = verify_evidence(page, candidate.evidence.quote)
            evidence = Evidence(
                document_id=page.document_id,
                page_number=page.page_number,
                quote=candidate.evidence.quote,
                char_start=start,
                char_end=end,
            )
            status = "VALID" if grounded and not candidate.ambiguous else "AMBIGUOUS"
            if not grounded:
                status = "EVIDENCE_FAILED"
                failures.append(
                    ExtractionFailure(
                        f"Evidence quote was not found on page {page.page_number}",
                        page.page_number,
                        "evidence_verification",
                    )
                )
            facts.append(
                Fact(
                    id=str(uuid4()),
                    subject=candidate.subject,
                    predicate=candidate.predicate,
                    object=candidate.object_value,
                    fact_type=candidate.fact_type,
                    value=candidate.original_value,
                    normalized_value=candidate.normalized_value,
                    unit=candidate.unit,
                    time=candidate.time,
                    scope=candidate.scope,
                    location=candidate.location,
                    qualifiers={**candidate.qualifiers, "currency": candidate.currency},
                    confidence=candidate.confidence,
                    evidence=evidence,
                    status=status,
                )
            )
        return facts, failures

    @staticmethod
    def _prompt(page: Page) -> str:
        return f"""Extract meaningful facts from this PDF page.
Only use information explicitly supported by the page. Do not infer missing values.
Discover predicates dynamically; do not limit extraction to a fixed fact list.
Every fact must include an exact quote from this page and its page number.
Capture subject, predicate, original value, units, currency, time, scope, location,
qualifiers, confidence from 0 to 1, and whether the interpretation is ambiguous.
Return an object with a facts array matching the requested JSON schema.

DOCUMENT ID: {page.document_id}
PAGE NUMBER: {page.page_number}
PAGE TEXT:
{page.text}
"""