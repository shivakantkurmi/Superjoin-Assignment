from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..models import Evidence, Fact
from .gemini_client import GeminiClient, GeminiResponseError
from ..reasoning.relationships import RelationshipResult, RelationshipType


class RelationshipPayload(BaseModel):
    relationship_type: RelationshipType
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1)
    factors: list[str] = Field(default_factory=list)


class RelationshipReasoner:
    """Use Gemini only when deterministic comparison cannot resolve a pair."""

    def __init__(self, client: GeminiClient) -> None:
        self.client = client

    def reason(
        self,
        first: Fact,
        second: Fact,
        evidence: tuple[Evidence | None, Evidence | None] = (None, None),
    ) -> RelationshipResult:
        try:
            payload = RelationshipPayload.model_validate(
                self.client.generate_json(self._prompt(first, second, evidence), RelationshipPayload)
            )
        except (GeminiResponseError, ValueError) as exc:
            return RelationshipResult(
                RelationshipType.AMBIGUOUS,
                0.2,
                f"Gemini could not resolve this relationship: {exc}",
                ("reasoning failure",),
            )
        return RelationshipResult(
            payload.relationship_type,
            payload.confidence,
            payload.explanation,
            tuple(payload.factors),
        )

    @staticmethod
    def _prompt(
        first: Fact,
        second: Fact,
        evidence: tuple[Evidence | None, Evidence | None],
    ) -> str:
        first_evidence, second_evidence = evidence
        return f"""Classify the relationship between two extracted facts.
Use only the facts and evidence below. Check subject, predicate, period, scope,
location, measurement definition, qualifiers, and normalized values before deciding.
Return JSON matching the requested schema. Do not invent missing context.
Allowed relationship_type values: CORROBORATES, CONTRADICTS, RECONCILES, UNRELATED, AMBIGUOUS.
The explanation must name the relevant contextual reason and remain grounded in these facts.

FACT A:
{_fact_summary(first)}
EVIDENCE A:
{_evidence_summary(first_evidence)}

FACT B:
{_fact_summary(second)}
EVIDENCE B:
{_evidence_summary(second_evidence)}
"""


def _fact_summary(fact: Fact) -> str:
    return str(
        {
            "subject": fact.subject,
            "predicate": fact.predicate,
            "value": fact.value,
            "normalized_value": fact.normalized_value,
            "unit": fact.unit,
            "time": fact.time,
            "scope": fact.scope,
            "location": fact.location,
            "qualifiers": fact.qualifiers,
        }
    )


def _evidence_summary(evidence: Evidence | None) -> str:
    if evidence is None:
        return "No evidence supplied"
    return f"document={evidence.document_id}, page={evidence.page_number}, quote={evidence.quote!r}"