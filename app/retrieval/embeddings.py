from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend cannot be used."""


class FactEmbedder:
    model_name = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self, encode: Callable[[list[str]], Any] | None = None) -> None:
        self._encode = encode
        self._model = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - setup failure path
                raise EmbeddingError("sentence-transformers is not installed") from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: list[str]) -> Any:
        if self._encode:
            return self._encode(texts)
        return self._load_model().encode(texts, normalize_embeddings=True)


def fact_text(fact: Any) -> str:
    time_label = fact.time.get("label", "") if fact.time else ""
    qualifiers = " ".join(f"{key} {value}" for key, value in fact.qualifiers.items())
    return " ".join(
        str(value)
        for value in (fact.subject, fact.predicate, fact.value, fact.unit, time_label, fact.scope, fact.location, qualifiers)
        if value
    )


class VectorIndex:
    """FAISS candidate index; Supabase remains the authoritative fact store."""

    def __init__(self, embedder: FactEmbedder, dimension: int | None = None) -> None:
        self.embedder = embedder
        self._fact_ids: list[str] = []
        self._index = None
        self._dimension = dimension

    def _ensure_index(self, dimension: int) -> None:
        if self._index is not None:
            return
        try:
            import faiss
        except ImportError as exc:  # pragma: no cover - setup failure path
            raise EmbeddingError("faiss-cpu is not installed") from exc
        self._dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)

    def add_facts(self, facts: Iterable[Any]) -> None:
        facts = list(facts)
        if not facts:
            return
        vectors = self.embedder.encode([fact_text(fact) for fact in facts])
        self._ensure_index(len(vectors[0]))
        self._index.add(vectors)
        self._fact_ids.extend(fact.id for fact in facts)

    def search_similar(self, fact: Any, top_k: int = 5) -> list[tuple[str, float]]:
        if self._index is None or not self._fact_ids:
            return []
        vector = self.embedder.encode([fact_text(fact)])
        scores, positions = self._index.search(vector, min(top_k + 1, len(self._fact_ids)))
        return [
            (self._fact_ids[position], float(score))
            for position, score in zip(positions[0], scores[0])
            if position >= 0 and self._fact_ids[position] != fact.id
        ][:top_k]

    def save(self, directory: str | Path) -> None:
        if self._index is None:
            return
        try:
            import faiss
        except ImportError as exc:  # pragma: no cover
            raise EmbeddingError("faiss-cpu is not installed") from exc
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(target / "index.faiss"))
        (target / "metadata.json").write_text(
            __import__("json").dumps({"fact_ids": self._fact_ids}), encoding="utf-8"
        )