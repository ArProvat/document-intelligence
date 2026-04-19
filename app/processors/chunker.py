import uuid
from typing import List

from ...config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS
from app.models.schemas import DocumentChunk, PageResult


def _split_into_sentences(text: str) -> List[str]:
    """
    Simple sentence splitter that preserves legal sentence endings.
    Avoids splitting on abbreviations like "No.", "Sec.", "v.", "et al."
    """
    import re
    # Protect common abbreviations temporarily
    abbrev_patterns = [
        (r'\bNo\.',    'No__DOT__'),
        (r'\bSec\.',   'Sec__DOT__'),
        (r'\bArt\.',   'Art__DOT__'),
        (r'\bvs?\.',   'v__DOT__'),
        (r'\bet al\.', 'et_al__DOT__'),
        (r'\be\.g\.',  'eg__DOT__'),
        (r'\bi\.e\.',  'ie__DOT__'),
        (r'\bMr\.',    'Mr__DOT__'),
        (r'\bMs\.',    'Ms__DOT__'),
        (r'\bDr\.',    'Dr__DOT__'),
    ]
    for pattern, replacement in abbrev_patterns:
        text = re.sub(pattern, replacement, text)

    # Split on sentence endings
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)

    # Restore abbreviations
    restored = []
    for s in sentences:
        for pattern, replacement in abbrev_patterns:
            s = s.replace(replacement, pattern.replace(r'\b', '').replace('\\', ''))
        restored.append(s.strip())

    return [s for s in restored if s]


def chunk_pages(pages: List[PageResult], doc_id: str) -> List[DocumentChunk]:
    """
    Produces overlapping text chunks across all pages, respecting sentence
    boundaries. Each chunk carries page provenance metadata.

    Strategy:
    - Concatenate page texts with a page-break marker.
    - Walk forward by CHUNK_SIZE_CHARS, stepping back to the nearest sentence
      boundary so chunks don't cut mid-sentence.
    - Overlap by CHUNK_OVERLAP_CHARS to preserve context across chunk edges.
    """
    chunks: List[DocumentChunk] = []

    # Build full text with page boundary markers
    page_boundaries: List[tuple[int, int, int]] = []  # (char_start, char_end, page_number)
    full_text_parts: List[str] = []
    cursor = 0

    for page in pages:
        text = page.cleaned_text
        if not text.strip():
            continue
        start = cursor
        full_text_parts.append(text)
        cursor += len(text) + 1   # +1 for the newline separator
        page_boundaries.append((start, cursor - 1, page.page_number))

    full_text = "\n".join(full_text_parts)
    total_len = len(full_text)

    if total_len == 0:
        return chunks

    def char_to_page(char_idx: int) -> int:
        for start, end, pg in page_boundaries:
            if start <= char_idx <= end:
                return pg
        return page_boundaries[-1][2] if page_boundaries else 1

    # Sliding window chunking
    pos = 0
    chunk_index = 0

    while pos < total_len:
        end = min(pos + CHUNK_SIZE_CHARS, total_len)

        # Walk back to the nearest sentence boundary (period, newline)
        if end < total_len:
            for boundary_char in ['. ', '.\n', '\n\n', '\n']:
                boundary_pos = full_text.rfind(boundary_char, pos, end)
                if boundary_pos != -1 and boundary_pos > pos + (CHUNK_SIZE_CHARS // 2):
                    end = boundary_pos + len(boundary_char)
                    break

        chunk_text = full_text[pos:end].strip()

        if chunk_text:
            page_start = char_to_page(pos)
            page_end   = char_to_page(end - 1)

            chunks.append(DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=chunk_text,
                page_start=page_start,
                page_end=page_end,
                char_start=pos,
                char_end=end,
                chunk_index=chunk_index,
                metadata={
                    "word_count": len(chunk_text.split()),
                    "char_count": len(chunk_text),
                },
            ))
            chunk_index += 1

        # Advance with overlap
        pos = max(pos + 1, end - CHUNK_OVERLAP_CHARS)

    return chunks
