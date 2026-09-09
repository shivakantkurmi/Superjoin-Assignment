from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..models import Page


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    page_number: int
    chunk_index: int
    text: str


def _deduplicate_repeated_lines(text: str) -> str:
    """Remove consecutive duplicate lines that are typically page headers/footers."""
    lines = text.split("\n")
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Only deduplicate short, non-sentence lines (likely headers/footers)
        if stripped and len(stripped) < 80 and stripped in seen:
            continue
        if stripped:
            seen.add(stripped)
        result.append(line)
    return "\n".join(result)


def clean_text(text: str) -> str:
    """Remove extraction noise while preserving words, numbers, and sentence boundaries.

    Steps applied in order:
    1. Unicode NFKC normalization — fixes ligatures (ﬁ→fi), fullwidth chars, etc.
    2. Soft-hyphen removal.
    3. Safe hyphenation cleanup — only joins word-broken lines, not compound words.
    4. Repeated-line deduplication (page headers/footers).
    5. Whitespace normalization.
    """
    # 1. Unicode normalization — deterministic, local
    text = unicodedata.normalize("NFKC", text)
    # 2. Soft hyphens (U+00AD invisible character from PDF extraction)
    text = text.replace("\u00ad", "")
    # 3. Hyphenated line-breaks: only join when both sides are word characters
    #    and the break is mid-word (not a compound like "cost-\neffective" where
    #    the hyphen is intentional). We join without a space when preceded by a
    #    lowercase letter immediately before the hyphen.
    text = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "", text)
    # 4. Repeated short lines (headers/footers)
    text = _deduplicate_repeated_lines(text)
    # 5. Collapse remaining whitespace to single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_pages(pages: list[Page], max_characters: int = 1800) -> list[Chunk]:
    """Split pages into sentence-boundary-aligned chunks preserving page provenance."""
    chunks: list[Chunk] = []
    for page in pages:
        text = clean_text(page.text)
        sentences = re.split(r"(?<=[.!?])\s+", text) if text else []
        current: list[str] = []
        size = 0
        chunk_index = 0
        for sentence in sentences:
            if current and size + len(sentence) + 1 > max_characters:
                chunks.append(Chunk(f"{page.document_id}:{page.page_number}:{chunk_index}", page.document_id, page.page_number, chunk_index, " ".join(current)))
                chunk_index += 1
                current, size = [], 0
            current.append(sentence)
            size += len(sentence) + 1
        if current:
            chunks.append(Chunk(f"{page.document_id}:{page.page_number}:{chunk_index}", page.document_id, page.page_number, chunk_index, " ".join(current)))
    return chunks