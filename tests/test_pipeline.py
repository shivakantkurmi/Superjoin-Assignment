import numpy as np

from app.llm.fact_extractor import FactExtractor
from app.llm.gemini_client import GeminiClient
from app.models import Page
from app.pipeline import ProcessingPipeline
from app.retrieval.embeddings import FactEmbedder, VectorIndex


def extraction_response(prompt, schema):
    return {
        "facts": [
            {
                "subject": "ABC Ltd",
                "predicate": "revenue",
                "object_value": "INR 125 crore",
                "fact_type": "revenue",
                "original_value": "INR 125 crore",
                "confidence": 0.9,
                "evidence": {"quote": "Revenue was INR 125 crore.", "page": 1},
            }
        ]
    }


def test_pipeline_extracts_normalizes_and_stores_fact_for_future_candidates():
    extractor = FactExtractor(GeminiClient(generate=extraction_response))
    embedder = FactEmbedder(encode=lambda texts: np.ones((len(texts), 2), dtype="float32"))
    pipeline = ProcessingPipeline(extractor, VectorIndex(embedder))

    result = pipeline.process([Page("doc-1", 1, "Revenue was INR 125 crore.")])

    assert len(result.facts) == 1
    assert result.facts[0].normalized_value == 1250000000
    assert result.facts[0].evidence.quote == "Revenue was INR 125 crore."
    assert not result.failures