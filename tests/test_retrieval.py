import numpy as np
from decimal import Decimal

from app.models import Fact
from app.normalization import normalize_fact
from app.retrieval.embeddings import FactEmbedder, VectorIndex, fact_text


def make_fact(fact_id: str, subject: str, value: str, period: str = "FY2024") -> Fact:
    return Fact(
        id=fact_id,
        subject=subject,
        predicate="Revenue",
        value=value,
        unit="crore",
        time={"label": period},
        scope="company",
    )


def test_normalize_fact_preserves_source_value_and_adds_canonical_fields():
    fact = normalize_fact(make_fact("a", "ABC Ltd.", "₹12.5 crore"))
    assert fact.value == "₹12.5 crore"
    assert fact.normalized_value == Decimal("125000000")
    assert fact.subject == "abc ltd"
    assert fact.time["year"] == "2024"


def test_fact_text_contains_context_not_only_the_number():
    text = fact_text(make_fact("a", "ABC Ltd", "₹12.5 crore"))
    assert "ABC Ltd" in text
    assert "FY2024" in text


def test_vector_index_returns_top_candidate_and_excludes_query_fact():
    vectors = {
        "ABC Ltd Revenue ₹12.5 crore crore FY2024 company": [1.0, 0.0],
        "ABC Ltd Revenue ₹13 crore crore FY2024 company": [0.99, 0.01],
        "Other Co Revenue ₹12 crore crore FY2024 company": [0.0, 1.0],
    }

    def encode(texts):
        return np.array([vectors[text] for text in texts], dtype="float32")

    embedder = FactEmbedder(encode=encode)
    index = VectorIndex(embedder)
    first = make_fact("a", "ABC Ltd", "₹12.5 crore")
    second = make_fact("b", "ABC Ltd", "₹13 crore")
    third = make_fact("c", "Other Co", "₹12 crore")
    index.add_facts([first, second, third])

    assert index.search_similar(first, top_k=2)[0][0] == "b"
    assert all(fact_id != "a" for fact_id, _ in index.search_similar(first, top_k=2))