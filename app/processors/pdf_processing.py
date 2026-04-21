import logging
from pathlib import Path
from typing import List, Tuple
from PIL import Image
import io
import fitz                          # PyMuPDF
import pdfplumber
from pdf2image import convert_from_path

from config import (
    NATIVE_TEXT_MIN_CHARS, MIN_TEXT_LENGTH_PER_PAGE,
    OCR_DPI, OCR_CONFIDENCE_THRESHOLD,
)
from app.models.schemas import ExtractionMethod, PageResult
from app.processors.text_cleaner import clean_text, estimate_confidence_from_text
from app.processors.image_processor import ocr_pil_image

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_page_scanned(page_text: str) -> bool:
    """Return True if the extracted text is too short to be real content."""
    return len(page_text.strip()) < NATIVE_TEXT_MIN_CHARS


def _extract_tables_from_page(pdf_path: Path, page_number: int) -> List[List[List[str]]]:
    """
    Use pdfplumber to extract tables from a single page.
    Returns list of tables; each table is a list of rows; each row a list of cells.
    """
    tables = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number - 1 < len(pdf.pages):
                page = pdf.pages[page_number - 1]
                raw_tables = page.extract_tables()
                for tbl in (raw_tables or []):
                    cleaned_table = [
                        [cell if cell is not None else "" for cell in row]
                        for row in tbl
                    ]
                    tables.append(cleaned_table)
    except Exception as exc:
        logger.warning("Table extraction failed on page %d: %s", page_number, exc)
    return tables


def _native_page_to_result(
    fitz_page,
    page_number: int,
    pdf_path: Path,
) -> PageResult:
    """Extract text from a PDF page that has a real text layer."""
    raw_text = fitz_page.get_text("text")       # plain text
    cleaned_text, warnings = clean_text(raw_text)
    confidence = estimate_confidence_from_text(raw_text, cleaned_text)
    tables = _extract_tables_from_page(pdf_path, page_number)

    return PageResult(
        page_number=page_number,
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        confidence=confidence,
        extraction_method=ExtractionMethod.NATIVE_TEXT,
        word_count=len(cleaned_text.split()),
        has_tables=bool(tables),
        tables=tables,
        warnings=warnings,
    )


# ── Main PDF processor ────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path) -> Tuple[List[PageResult], ExtractionMethod]:
    """
    Process a PDF file page by page.

    Strategy:
      1. Open with PyMuPDF.
      2. For each page, check if real text exists.
         - If yes → extract natively (fast, accurate).
         - If no  → convert page to image at OCR_DPI and run Tesseract.
      3. Tables are always attempted via pdfplumber (even on native pages).

    Returns (list_of_page_results, overall_extraction_method).
    """
    pages: List[PageResult] = []
    scanned_count  = 0
    native_count   = 0

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    logger.info("Processing PDF: %s (%d pages)", pdf_path.name, total_pages)

    # Pre-convert ALL pages to images once (avoids re-opening per page)
    # Only do this if the PDF appears to be mostly scanned
    native_texts = [doc[i].get_text("text") for i in range(total_pages)]
    scanned_pages = [i for i, t in enumerate(native_texts) if _is_page_scanned(t)]
    needs_ocr = len(scanned_pages) > 0

    pil_images: dict[int, object] = {}
    if needs_ocr:
        logger.info("Converting %d page(s) to images for OCR...", len(scanned_pages))
        try:
            all_images = convert_from_path(
                str(pdf_path),
                dpi=OCR_DPI,
                first_page=1,
                last_page=total_pages,
            )
            pil_images = {i: img for i, img in enumerate(all_images)}
        except Exception as exc:
            logger.error("pdf2image conversion failed: %s", exc)

    for i in range(total_pages):
        page_number = i + 1
        page_text   = native_texts[i]

        if _is_page_scanned(page_text):
            # ── Scanned page: use OCR ──────────────────────────────────────
            scanned_count += 1
            if i in pil_images:
                result = ocr_pil_image(pil_images[i], page_number)
            else:
                # Fallback: try to render via PyMuPDF directly
                try:
                    mat  = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
                    pix  = doc[i].get_pixmap(matrix=mat, alpha=False)
                    img  = Image.open(io.BytesIO(pix.tobytes("png")))
                    result = ocr_pil_image(img, page_number)
                except Exception as exc:
                    logger.error("Page %d OCR failed: %s", page_number, exc)
                    result = PageResult(
                        page_number=page_number,
                        raw_text="",
                        cleaned_text="",
                        confidence=0.0,
                        extraction_method=ExtractionMethod.OCR_SCAN,
                        word_count=0,
                        warnings=[f"OCR failed: {exc}"],
                    )
        else:
            # ── Native text page ──────────────────────────────────────────
            native_count += 1
            result = _native_page_to_result(doc[i], page_number, pdf_path)

        # Flag pages with almost no text even after processing
        if len(result.cleaned_text.strip()) < MIN_TEXT_LENGTH_PER_PAGE:
            result.warnings.append(
                f"Page {page_number}: very little text ({result.word_count} words) — "
                "may be blank, a diagram, or a failed extraction"
            )

        pages.append(result)

    doc.close()

    # Determine overall extraction method
    if native_count == 0:
        method = ExtractionMethod.OCR_SCAN
    elif scanned_count == 0:
        method = ExtractionMethod.NATIVE_TEXT
    else:
        method = ExtractionMethod.HYBRID

    logger.info(
        "PDF processed: %d native, %d OCR pages. Method: %s",
        native_count, scanned_count, method,
    )
    return pages, method
