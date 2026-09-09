from __future__ import annotations

import re
from uuid import uuid4

from ..ingestion import verify_evidence
from ..models import Evidence, Fact, Page
from .chunking import clean_text


# ── Pattern library ──────────────────────────────────────────────────────────

# Numerical values: optional currency prefix, number, optional scale / %
_NUMBER = re.compile(
    r"(?:₹|\$|€|£|INR|USD|EUR|GBP|Rs\.?)\s*[-+]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:thousand|million|billion|crore|lakh|mn|bn|k|%)?|"
    r"[-+]?\d[\d,]*(?:\.\d+)?\s*(?:thousand|million|billion|crore|lakh|mn|bn|k|%)",
    re.IGNORECASE,
)

# Semantic verbs that signal a factual statement even without a number
_SEMANTIC = re.compile(
    r"\b(is|was|were|has|had|located|appointed|resigned|operates|owns|serves|"
    r"increased|decreased|grew|declined|reported|reached|stood|totalled?|"
    r"exceeded|achieved|represents?|accounts?\s+for)\b",
    re.IGNORECASE,
)

# Fiscal / calendar period labels
_PERIOD = re.compile(
    r"\b(?:fy\s*\d{2,4}|q[1-4]\s*(?:fy)?\s*\d{2,4}|"
    r"(?:year|quarter|half[- ]year)\s+ended?\s+\w+\s+\d{4}|"
    r"\d{4}[-\u2013]\d{2,4}|fy\s*\d{4})\b",
    re.IGNORECASE,
)

# Currency codes and symbols
_CURRENCY = re.compile(r"\b(INR|USD|EUR|GBP|Rs\.?)\b|[₹$€£]", re.IGNORECASE)

# Measurement units
_UNIT = re.compile(
    r"\b(thousand|million|billion|crore|lakh|mn|bn|k|percent|%|"
    r"km|kg|tonne|units?|pieces?|shipments?)\b",
    re.IGNORECASE,
)

# Scope qualifiers
_SCOPE = re.compile(
    r"\b(consolidated|standalone|segment|group|parent|subsidiary|"
    r"company|division|region|total)\b",
    re.IGNORECASE,
)

_STOP_WORDS = frozenset({
    "the", "a", "an", "was", "were", "is", "has", "had",
    "of", "for", "in", "during", "to", "at", "by", "on",
    "and", "or", "its", "their", "our",
})


class DeterministicFactExtractor:
    """Create grounded candidates locally using regex / NLP.

    Extraction philosophy: HIGH RECALL over precision — include borderline
    sentences and let the deterministic comparison + LLM stages filter them.
    No LLM is called here.
    """

    def extract_page(self, page: Page) -> tuple[list[Fact], list[object]]:
        facts: list[Fact] = []
        cleaned = clean_text(page.text)
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            sentence = sentence.strip()
            if not sentence or len(sentence) < 8:
                continue
            number = _NUMBER.search(sentence)
            # Accept sentence if it has a numeric value OR a semantic verb
            if number is None and not _SEMANTIC.search(sentence):
                continue

            value = number.group(0).strip() if number else None
            period_match = _PERIOD.search(sentence)
            time: dict[str, str | None] = (
                {"label": period_match.group(0)} if period_match else {}
            )
            currency_match = _CURRENCY.search(sentence)
            unit_match = _UNIT.search(sentence)
            scope_match = _SCOPE.search(sentence)

            predicate = self._predicate(sentence, number.start() if number else len(sentence))
            subject = self._subject(sentence)

            grounded, start, end = verify_evidence(page, sentence)
            facts.append(
                Fact(
                    id=str(uuid4()),
                    subject=subject,
                    predicate=predicate,
                    object=value or sentence[:80],
                    fact_type=self._fact_type(predicate, value),
                    value=value,
                    unit=unit_match.group(0).lower() if unit_match else None,
                    time=time,
                    scope=scope_match.group(0).lower() if scope_match else None,
                    qualifiers=(
                        {"currency": currency_match.group(0).upper().rstrip(".")}
                        if currency_match
                        else {}
                    ),
                    confidence=0.65 if number else 0.45,
                    evidence=Evidence(
                        page.document_id,
                        page.page_number,
                        sentence,
                        char_start=start,
                        char_end=end,
                    ),
                    status="VALID" if grounded else "EVIDENCE_FAILED",
                )
            )
        return facts, []

    @staticmethod
    def _subject(sentence: str) -> str:
        """Return the first capitalized multi-word phrase as the likely subject."""
        match = re.search(r"\b[A-Z][A-Za-z&.\-]*(?:\s+[A-Z][A-Za-z&.\-]*){0,3}", sentence)
        return match.group(0) if match else "document subject"

    @staticmethod
    def _predicate(sentence: str, end: int) -> str:
        """Compact predicate from words immediately before the numeric value."""
        words = [w for w in sentence[:end].split()[-8:] if w.casefold() not in _STOP_WORDS]
        return " ".join(words).strip(" ,:;") or "statement"

    @staticmethod
    def _fact_type(predicate: str, value: str | None) -> str:
        """Coarse fact type inferred from predicate keywords."""
        pred_lower = predicate.lower()
        if any(kw in pred_lower for kw in ("revenue", "turnover", "sales", "income")):
            return "revenue"
        if any(kw in pred_lower for kw in ("profit", "ebitda", "earnings", "margin")):
            return "profitability"
        if any(kw in pred_lower for kw in ("growth", "increase", "decrease", "change")):
            return "growth"
        if value and "%" in value:
            return "percentage"
        return "metric"