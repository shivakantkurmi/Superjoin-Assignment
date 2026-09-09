from decimal import Decimal

from app.ingestion import verify_evidence
from app.models import Page
from app.normalization import canonical_text, normalize_number, normalize_period


def test_number_scales_share_a_canonical_value():
    assert normalize_number("₹12.5 crore") == Decimal("125000000")
    assert normalize_number("125 million", "INR") == Decimal("125000000")


def test_number_commas_are_supported():
    assert normalize_number("1,250") == Decimal("1250")


def test_period_keeps_original_and_extracts_year():
    assert normalize_period("year ended March 31, 2024") == {
        "label": "year ended March 31, 2024",
        "year": "2024",
    }


def test_canonical_text_only_removes_surface_punctuation():
    assert canonical_text("ABC Ltd.") == "abc ltd"


def test_evidence_verification_returns_offsets():
    page = Page("doc-1", 2, "Revenue for FY2024 was INR 125 crore.")
    assert verify_evidence(page, "INR 125 crore") == (True, 23, 36)


def test_evidence_verification_rejects_ungrounded_quote():
    page = Page("doc-1", 2, "Revenue for FY2024 was INR 125 crore.")
    assert verify_evidence(page, "INR 999 crore") == (False, None, None)


def test_lakh_scale_normalizes_correctly():
    """1 lakh = 100,000"""
    assert normalize_number("5 lakh") == Decimal("500000")
    assert normalize_number("10.5 lakh") == Decimal("1050000")


def test_percentage_normalized_to_face_value():
    """Percentages should return the numeric value (e.g. 12.5% → 12.5)."""
    assert normalize_number("12.5%") == Decimal("12.5")
    assert normalize_number("100%") == Decimal("100")