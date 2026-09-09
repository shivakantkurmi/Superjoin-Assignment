from __future__ import annotations

import json
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
                raise EmbeddingError(f"sentence-transformers is not installed: {exc}") from exc
            try:
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
            except Exception:
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
    """FAISS candidate index; Supabase remains the authoritative fact store.

    Only facts whose cosine similarity score exceeds ``similarity_threshold``
    are returned by :meth:`search_similar`, preventing unrelated facts from
    reaching the expensive deterministic comparison and LLM reasoning stages.
    """

    def __init__(
        self,
        embedder: FactEmbedder,
        dimension: int | None = None,
        similarity_threshold: float = 0.50,
    ) -> None:
        self.embedder = embedder
        self._fact_ids: list[str] = []
        self._index = None
        self._dimension = dimension
        self.similarity_threshold = similarity_threshold

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
        """Encode and add facts; silently skip any fact whose ID is already in the index."""
        facts = list(facts)
        if not facts:
            return
        existing_ids = set(self._fact_ids)
        new_facts = [f for f in facts if f.id not in existing_ids]
        if not new_facts:
            return
        vectors = self.embedder.encode([fact_text(f) for f in new_facts])
        self._ensure_index(len(vectors[0]))
        self._index.add(vectors)
        self._fact_ids.extend(f.id for f in new_facts)

    def rebuild(self, facts: Iterable[Any]) -> None:
        """Replace the index contents after facts are removed from the store."""
        self._index = None
        self._fact_ids = []
        self.add_facts(facts)

    def search_similar_batch(
        self, facts: list[Any], top_k: int = 5, similarity_threshold: float | None = None
    ) -> list[list[tuple[str, float]]]:
        """Search similar candidates for multiple facts in a single batched inference pass."""
        if not facts:
            return []
        if self._index is None or not self._fact_ids:
            return [[] for _ in facts]
        threshold = similarity_threshold if similarity_threshold is not None else self.similarity_threshold
        vectors = self.embedder.encode([fact_text(fact) for fact in facts])
        k = min(top_k + 1, len(self._fact_ids))
        scores, positions = self._index.search(vectors, k)
        results = []
        for fact, row_scores, row_positions in zip(facts, scores, positions):
            candidates = [
                (self._fact_ids[position], float(score))
                for position, score in zip(row_positions, row_scores)
                if position >= 0
                and self._fact_ids[position] != fact.id
                and float(score) >= threshold
            ][:top_k]
            results.append(candidates)
        return results

    def search_similar(
        self, fact: Any, top_k: int = 5, similarity_threshold: float | None = None
    ) -> list[tuple[str, float]]:
        """Return up to ``top_k`` (fact_id, score) pairs above the similarity threshold.

        The threshold defaults to the instance-level setting so tests and
        callers can override it per-query when needed.
        """
        matches = self.search_similar_batch([fact], top_k=top_k, similarity_threshold=similarity_threshold)
        return matches[0] if matches else []

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
            json.dumps({"fact_ids": self._fact_ids, "similarity_threshold": self.similarity_threshold}),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path, embedder: FactEmbedder) -> "VectorIndex":
        """Reconstruct a VectorIndex from a previously saved FAISS index directory."""
        try:
            import faiss
        except ImportError as exc:  # pragma: no cover
            raise EmbeddingError("faiss-cpu is not installed") from exc
        target = Path(directory)
        meta = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
        index = faiss.read_index(str(target / "index.faiss"))
        instance = cls(embedder, similarity_threshold=meta.get("similarity_threshold", 0.50))
        instance._index = index
        instance._fact_ids = meta["fact_ids"]
        instance._dimension = index.d
        return instance
