import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from ...config import ALLOWED_EXTENSIONS, OCR_CONFIDENCE_THRESHOLD, MIN_TEXT_LENGTH_PER_PAGE
from app.models.schemas import (
    ProcessedDocument, ProcessingWarning, ExtractionMethod, DocumentType,
)
from .pdf_processing   import process_pdf
from .image_processor import ocr_image_file
from .text_cleaner    import clean_text
from .doc_classifier  import classify_document
from .entity_extractor import extract_entities

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
_PDF_EXTENSIONS   = {".pdf"}


def _compute_quality_score(pages, avg_conf: float, warnings: list) -> float:
    """
    Composite quality score (0–1) based on:
      - Average OCR confidence (50%)
      - Proportion of pages with usable text (30%)
      - Penalty for warnings (20%)
    """
    usable_pages = sum(1 for p in pages if len(p.cleaned_text.strip()) >= MIN_TEXT_LENGTH_PER_PAGE)
    usable_ratio = usable_pages / max(len(pages), 1)

    warning_penalty = min(len(warnings) * 0.05, 0.2)

    score = (avg_conf * 0.5) + (usable_ratio * 0.3) + (0.2 - warning_penalty)
    return round(min(max(score, 0.0), 1.0), 3)


def process_document(file_path: Path, original_filename: str) -> ProcessedDocument:
    """
    Full pipeline:
      1. Route by file type → extract pages
      2. Classify document type
      3. Extract entities (dates, parties, amounts, …)
      4. Chunk for downstream retrieval
      5. Assemble ProcessedDocument
    """
    doc_id = str(uuid.uuid4())
    suffix = Path(original_filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")

    # ── Step 1: Extract pages ────────────────────────────────────────────────
    pages = []
    extraction_method = ExtractionMethod.NATIVE_TEXT

    if suffix in _PDF_EXTENSIONS:
        pages, extraction_method = process_pdf(file_path)

    elif suffix in _IMAGE_EXTENSIONS:
        page_result = ocr_image_file(file_path, page_number=1)
        pages = [page_result]
        extraction_method = ExtractionMethod.OCR_IMAGE

    else:
        raise ValueError(f"Unhandled extension: {suffix}")

    # ── Step 2: Aggregate text and confidence ────────────────────────────────
    full_text = "\n\n".join(p.cleaned_text for p in pages if p.cleaned_text.strip())
    confidences = [p.confidence for p in pages]
    avg_confidence = round(sum(confidences) / max(len(confidences), 1), 3)

    low_confidence_pages = [
        p.page_number for p in pages
        if p.confidence < OCR_CONFIDENCE_THRESHOLD
    ]

    # ── Step 3: Classify ─────────────────────────────────────────────────────
    doc_type, type_confidence = classify_document(full_text)

    # ── Step 4: Entity extraction ─────────────────────────────────────────────
    entities = extract_entities(pages)

    # ── Step 5: Chunking ──────────────────────────────────────────────────────
    chunks = chunk_pages(pages, doc_id)

    # ── Step 6: Gather warnings ───────────────────────────────────────────────
    warnings: list[ProcessingWarning] = []

    if avg_confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(ProcessingWarning(
            code="LOW_OVERALL_CONFIDENCE",
            message=f"Average OCR confidence is low ({avg_confidence:.0%}). "
                    "Review extracted text carefully.",
        ))

    if doc_type == DocumentType.UNKNOWN:
        warnings.append(ProcessingWarning(
            code="UNKNOWN_DOC_TYPE",
            message="Could not determine document type. "
                    "Classification keywords may be absent.",
        ))

    for page in pages:
        for w in page.warnings:
            warnings.append(ProcessingWarning(
                code="PAGE_WARNING",
                message=w,
                page=page.page_number,
            ))

    if not full_text.strip():
        warnings.append(ProcessingWarning(
            code="NO_TEXT_EXTRACTED",
            message="No usable text could be extracted from this document.",
        ))

    is_usable = bool(full_text.strip()) and avg_confidence >= 0.2

    quality_score = _compute_quality_score(pages, avg_confidence, warnings)

    logger.info(
        "doc_id=%s | type=%s (%.0f%%) | pages=%d | avg_conf=%.0f%% | "
        "chunks=%d | entities=%d | quality=%.2f",
        doc_id, doc_type, type_confidence * 100,
        len(pages), avg_confidence * 100,
        len(chunks), len(entities), quality_score,
    )

    return ProcessedDocument(
        doc_id=doc_id,
        filename=original_filename,
        file_type=suffix.lstrip("."),
        file_size_bytes=file_path.stat().st_size,
        processed_at=datetime.now(timezone.utc),
        doc_type=doc_type,
        doc_type_confidence=type_confidence,
        extraction_method=extraction_method,
        total_pages=len(pages),
        avg_confidence=avg_confidence,
        low_confidence_pages=low_confidence_pages,
        full_text=full_text,
        pages=pages,
        entities=entities,
        chunks=chunks,
        warnings=warnings,
        is_usable=is_usable,
        quality_score=quality_score,
    )
