from __future__ import annotations

from typing import Any


class MemoryStore:
    """Small local store for API tests and development without Supabase credentials."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, list[dict[str, Any]]] = {}
        self.facts: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def add_document(self, document: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        self.documents[document["id"]] = document
        self.pages[document["id"]] = pages

    def add_processing_result(
        self,
        document_id: str,
        facts: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        status: str,
    ) -> None:
        self.facts.extend(facts)
        self.relationships.extend(relationships)
        self.documents[document_id]["facts_count"] = len(facts)
        self.documents[document_id]["relationships_count"] = len(relationships)
        self.documents[document_id]["status"] = status

    def add_processing_error(self, document_id: str, message: str) -> None:
        self.documents[document_id]["status"] = "FAILED"
        self.errors.append({"document_id": document_id, "message": message})

    def knowledge_layer(self) -> dict[str, Any]:
        return {
            "documents": list(self.documents.values()),
            "facts": self.facts,
            "relationships": self.relationships,
        }