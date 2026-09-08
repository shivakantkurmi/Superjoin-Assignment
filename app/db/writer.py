from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from ..models import Page
from ..pipeline import ProcessingResult, fact_to_dict
from .repository import SupabaseRepository


class SupabaseWriter:
    """Persist one completed processing result without owning extraction or reasoning."""

    def __init__(self, repository: SupabaseRepository) -> None:
        self.repository = repository

    def persist(
        self,
        document: Mapping[str, Any],
        pages: list[Page],
        result: ProcessingResult,
    ) -> None:
        self.repository.insert("documents", document)
        page_ids: dict[int, str] = {}
        for page in pages:
            page_id = str(uuid4())
            page_ids[page.page_number] = page_id
            self.repository.insert(
                "pages",
                {
                    "id": page_id,
                    "document_id": document["id"],
                    "page_number": page.page_number,
                    "text": page.text,
                    "is_scanned": page.is_scanned,
                },
            )

        for fact in result.facts:
            row = fact_to_dict(fact)
            evidence = row.pop("evidence")
            self.repository.insert(
                "facts",
                {
                    "id": fact.id,
                    "document_id": document["id"],
                    "fact_type": row["fact_type"],
                    "subject": row["subject"],
                    "predicate": row["predicate"],
                    "object_value": row["object"],
                    "normalized_value": row["normalized_value"],
                    "unit": row["unit"],
                    "currency": row["qualifiers"].get("currency"),
                    "time_label": (row["time"] or {}).get("label"),
                    "scope": row["scope"],
                    "location": row["location"],
                    "qualifiers": row["qualifiers"],
                    "confidence": row["confidence"],
                    "status": row["status"],
                },
            )
            if evidence:
                self.repository.insert(
                    "evidence",
                    {
                        "fact_id": fact.id,
                        "document_id": document["id"],
                        "page_id": page_ids[evidence["page_number"]],
                        "quote": evidence["quote"],
                        "char_start": evidence["char_start"],
                        "char_end": evidence["char_end"],
                        "verification_status": "VERIFIED" if fact.status == "VALID" else fact.status,
                    },
                )

        for fact_a_id, fact_b_id, relationship in result.relationships:
            self.repository.insert(
                "relationships",
                {
                    "fact_a_id": fact_a_id,
                    "fact_b_id": fact_b_id,
                    "relationship_type": relationship.relationship_type.value,
                    "confidence": relationship.confidence,
                    "explanation": relationship.explanation,
                    "reasoning_metadata": {"factors": list(relationship.factors)},
                },
            )