from __future__ import annotations

from typing import Any


class MemoryStore:
    """Small local store for API tests and development without Supabase credentials."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, list[dict[str, Any]]] = {}
        self.facts: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []

    def add_document(self, document: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        self.documents[document["id"]] = document
        self.pages[document["id"]] = pages

    def knowledge_layer(self) -> dict[str, Any]:
        return {
            "documents": list(self.documents.values()),
            "facts": self.facts,
            "relationships": self.relationships,
        }