from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .models import Fact


_SCALE = {
    "thousand": Decimal("1000"),
    "k": Decimal("1000"),
    "million": Decimal("1000000"),
    "mn": Decimal("1000000"),
    "m": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "b": Decimal("1000000000"),
    "crore": Decimal("10000000"),
    "cr": Decimal("10000000"),
    "lakh": Decimal("100000"),
    "l": Decimal("100000"),
}

# Percentage suffix — stored as-is in base units (i.e. 12.5% → Decimal("12.5"))
_PERCENT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%")


def normalize_number(raw: str, unit: str | None = None) -> Decimal | None:
    """Return a base-unit number when a recognized scale is explicit.

    Percentages are returned as their numeric face value (12.5% → 12.5).
    Currency and scale suffixes (crore, million, etc.) are expanded to base units.
    """
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip().lower()
    # Handle percentages first
    pct = _PERCENT_RE.fullmatch(cleaned.rstrip())
    if pct:
        try:
            return Decimal(pct.group(1))
        except InvalidOperation:
            return None
    match = re.fullmatch(
        r"(?:(?:inr|usd|eur|gbp|rs\.?)\s*)?(?:[₹$€£]\s*)?([-+]?\d+(?:\.\d+)?)\s*([a-z]+)?",
        cleaned,
    )
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    scale = match.group(2) or ""
    if not scale and unit:
        scale = unit.casefold().strip()
    return value * _SCALE.get(scale, Decimal("1"))


def canonical_text(value: str) -> str:
    """Normalize superficial entity/predicate spelling without entity resolution."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


def normalize_period(label: str) -> dict[str, str | None]:
    """Normalize common financial-year labels while retaining the original label."""
    original = label.strip()
    match = re.search(r"(?:fy\s*)?(20\d{2})", original.casefold())
    year = match.group(1) if match else None
    return {"label": original, "year": year}


def normalize_fact(fact: Fact) -> Fact:
    """Fill deterministic numeric and text normalizations without changing source values."""
    if isinstance(fact.value, str):
        fact.normalized_value = normalize_number(fact.value, fact.unit)
    fact.subject = canonical_text(fact.subject)
    fact.predicate = canonical_text(fact.predicate)
    label = fact.time.get("label") if fact.time else None
    if label:
        fact.time = normalize_period(label)
    return fact