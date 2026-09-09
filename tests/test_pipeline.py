"""Pipeline integration tests.

These tests verify the end-to-end processing path using the same
DeterministicFactExtractor that the default production pipeline uses.
No LLM calls are made.
"""
import numpy as np

from app.extraction.candidate_facts import DeterministicFactExtractor
from app.models import Page
from app.pipeline import ProcessingPipeline
from app.retrieval.embeddings import FactEmbedder, VectorIndex


def test_pipeline_extracts_normalizes_and_stores_fact_for_future_candidates():
    """The pipeline should produce at least one fact from a revenue sentence."""
    embedder = FactEmbedder(encode=lambda texts: np.ones((len(texts), 2), dtype="float32"))
    pipeline = ProcessingPipeline(DeterministicFactExtractor(), VectorIndex(embedder))

    result = pipeline.process([Page("doc-1", 1, "Revenue was INR 125 crore.")])

    assert len(result.facts) >= 1
    assert result.facts[0].evidence.quote is not None
    assert not result.failures


def test_pipeline_adds_cross_document_candidates_to_index():
    """Facts from successive documents should be indexed and retrieved as candidates."""
    embedder = FactEmbedder(encode=lambda texts: np.ones((len(texts), 2), dtype="float32"))
    pipeline = ProcessingPipeline(DeterministicFactExtractor(), VectorIndex(embedder))

    # Process first document — no prior facts, no relationships
    result1 = pipeline.process([Page("doc-1", 1, "Revenue was INR 125 crore in FY2024.")])
    assert len(result1.facts) >= 1

    # Process second document — facts from doc-1 are now in the index
    result2 = pipeline.process([Page("doc-2", 1, "Revenue was INR 125 crore in FY2024.")])
    assert len(result2.facts) >= 1
    # At least one relationship should be found across documents (corroboration or contradiction)
    assert len(result2.relationships) >= 1


def test_pipeline_ignores_stale_candidates_after_document_removal():
    embedder = FactEmbedder(encode=lambda texts: np.ones((len(texts), 2), dtype="float32"))
    pipeline = ProcessingPipeline(DeterministicFactExtractor(), VectorIndex(embedder))

    pipeline.process([Page("doc-1", 1, "Revenue was INR 125 crore in FY2024.")])
    pipeline.remove_document("doc-1")

    result = pipeline.process([Page("doc-2", 1, "Revenue was INR 125 crore in FY2024.")])

    assert result.facts
    assert not result.relationships