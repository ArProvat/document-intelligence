import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import ALLOWED_EXTENSIONS, MIN_TEXT_LENGTH_PER_PAGE, OCR_CONFIDENCE_THRESHOLD
from app.models.schemas import (
    DocumentType,
    ExtractionMethod,
    ProcessedDocument,
    ProcessingWarning,
)
from .chunker import chunk_pages
from .doc_classifier import classify_document
from .entity_extractor import extract_entities
from .image_processor import ocr_image_file
from .pdf_processing import process_pdf
from .xlsx_processor import process_xlsx

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
_PDF_EXTENSIONS = {".pdf"}
_SPREADSHEET_EXTENSIONS = {".xlsx"}


def _compute_quality_score(pages, avg_conf: float, warnings: list) -> float:
    usable_pages = sum(1 for p in pages if len(p.cleaned_text.strip()) >= MIN_TEXT_LENGTH_PER_PAGE)
    usable_ratio = usable_pages / max(len(pages), 1)
    warning_penalty = min(len(warnings) * 0.05, 0.2)
    score = (avg_conf * 0.5) + (usable_ratio * 0.3) + (0.2 - warning_penalty)
    return round(min(max(score, 0.0), 1.0), 3)


def process_document(file_path: Path, original_filename: str) -> ProcessedDocument:
    doc_id = str(uuid.uuid4())
    suffix = Path(original_filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")

    pages = []
    extraction_method = ExtractionMethod.NATIVE_TEXT

    if suffix in _PDF_EXTENSIONS:
        pages, extraction_method = process_pdf(file_path)
    elif suffix in _IMAGE_EXTENSIONS:
        pages = [ocr_image_file(file_path, page_number=1)]
        extraction_method = pages[0].extraction_method
    elif suffix in _SPREADSHEET_EXTENSIONS:
        pages = process_xlsx(file_path)
        extraction_method = ExtractionMethod.NATIVE_TEXT
    else:
        raise ValueError(f"Unhandled extension: {suffix}")

    full_text = "\n\n".join(p.cleaned_text for p in pages if p.cleaned_text.strip())
    confidences = [p.confidence for p in pages]
    avg_confidence = round(sum(confidences) / max(len(confidences), 1), 3)
    low_confidence_pages = [
        p.page_number for p in pages if p.confidence < OCR_CONFIDENCE_THRESHOLD
    ]

    doc_type, type_confidence = classify_document(full_text)
    entities = extract_entities(pages)
    chunks = chunk_pages(pages, doc_id)

    warnings: list[ProcessingWarning] = []

    if avg_confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(
            ProcessingWarning(
                code="LOW_OVERALL_CONFIDENCE",
                message=f"Average extraction confidence is low ({avg_confidence:.0%}). Review extracted text carefully.",
            )
        )

    if doc_type == DocumentType.UNKNOWN:
        warnings.append(
            ProcessingWarning(
                code="UNKNOWN_DOC_TYPE",
                message="Could not determine document type. Classification keywords may be absent.",
            )
        )

    for page in pages:
        for warning in page.warnings:
            warnings.append(
                ProcessingWarning(
                    code="PAGE_WARNING",
                    message=warning,
                    page=page.page_number,
                )
            )

    if not full_text.strip():
        warnings.append(
            ProcessingWarning(
                code="NO_TEXT_EXTRACTED",
                message="No usable text could be extracted from this document.",
            )
        )

    is_usable = bool(full_text.strip()) and avg_confidence >= 0.2
    quality_score = _compute_quality_score(pages, avg_confidence, warnings)

    logger.info(
        "doc_id=%s | type=%s (%.0f%%) | pages=%d | avg_conf=%.0f%% | chunks=%d | entities=%d | quality=%.2f",
        doc_id,
        doc_type,
        type_confidence * 100,
        len(pages),
        avg_confidence * 100,
        len(chunks),
        len(entities),
        quality_score,
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
