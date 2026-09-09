from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from ..extraction.chunking import chunk_pages
from ..models import Page
from ..pipeline import ProcessingResult, fact_to_dict
from .repository import SupabaseRepository


class SupabaseWriter:
    """Persist one completed processing result without owning extraction or reasoning."""

    def __init__(self, repository: SupabaseRepository) -> None:
        self.repository = repository

    def _insert_rows(self, table: str, rows: list[Mapping[str, Any]]) -> None:
        if not rows:
            return
        if hasattr(self.repository, "insert_many"):
            self.repository.insert_many(table, rows)
        else:
            for row in rows:
                self.repository.insert(table, row)

    def persist(
        self,
        document: Mapping[str, Any],
        pages: list[Page],
        result: ProcessingResult,
    ) -> None:
        page_ids: dict[int, str] = {}
        page_rows = []
        for page in pages:
            page_id = str(uuid4())
            page_ids[page.page_number] = page_id
            page_rows.append(
                {
                    "id": page_id,
                    "document_id": document["id"],
                    "page_number": page.page_number,
                    "text": page.text,
                    "is_scanned": page.is_scanned,
                }
            )
        self._insert_rows("pages", page_rows)

        chunk_rows = [
            {
                "id": chunk.id,
                "document_id": document["id"],
                "page_id": page_ids[chunk.page_number],
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "embedding_status": "COMPLETED",
            }
            for chunk in chunk_pages(pages)
        ]
        self._insert_rows("chunks", chunk_rows)

        fact_rows = []
        evidence_rows = []
        for fact in result.facts:
            row = fact_to_dict(fact)
            evidence = row.pop("evidence")
            fact_rows.append(
                {
                    "id": fact.id,
                    "document_id": document["id"],
                    "fact_type": row["fact_type"],
                    "subject": row["subject"],
                    "predicate": row["predicate"],
                    "object_value": str(row["object"]) if row["object"] is not None else None,
                    "normalized_value": row["normalized_value"],
                    "unit": row["unit"],
                    "currency": row["qualifiers"].get("currency"),
                    "time_label": (row["time"] or {}).get("label"),
                    "scope": row["scope"],
                    "location": row["location"],
                    "qualifiers": row["qualifiers"],
                    "confidence": row["confidence"],
                    "status": row["status"],
                }
            )
            if evidence:
                evidence_rows.append(
                    {
                        "fact_id": fact.id,
                        "document_id": document["id"],
                        "page_id": page_ids[evidence["page_number"]],
                        "chunk_id": evidence["chunk_id"],
                        "quote": evidence["quote"],
                        "char_start": evidence["char_start"],
                        "char_end": evidence["char_end"],
                        "verification_status": "VERIFIED" if fact.status == "VALID" else fact.status,
                    }
                )

        self._insert_rows("facts", fact_rows)
        self._insert_rows("evidence", evidence_rows)

        relationship_rows = [
            {
                "fact_a_id": fact_a_id,
                "fact_b_id": fact_b_id,
                "relationship_type": relationship.relationship_type.value,
                "confidence": relationship.confidence,
                "explanation": relationship.explanation,
                "reasoning_metadata": {"factors": list(relationship.factors)},
            }
            for fact_a_id, fact_b_id, relationship in result.relationships
        ]
        self._insert_rows("relationships", relationship_rows)