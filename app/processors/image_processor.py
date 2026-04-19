import io
import math
import logging
from pathlib import Path
from typing import Tuple, Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

from ...config import TESSERACT_LANG, TESSERACT_CONFIG, OCR_CONFIDENCE_THRESHOLD
from app.models.schemas import ExtractionMethod, PageResult
from app.processors.text_cleaner import clean_text

logger = logging.getLogger(__name__)



def _to_grayscale(img: Image.Image) -> Image.Image:
    return img.convert("L")


def _denoise(img: Image.Image) -> Image.Image:
    """Light Gaussian blur to suppress salt-and-pepper noise."""
    return img.filter(ImageFilter.GaussianBlur(radius=0.5))


def _enhance_contrast(img: Image.Image) -> Image.Image:
    """Boost contrast to help binarisation."""
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(2.0)


def _sharpen(img: Image.Image) -> Image.Image:
    """Unsharp-mask to improve edge crispness for OCR."""
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))


def _binarize(img: Image.Image) -> Image.Image:
    """
    Otsu-style adaptive binarization.
    PIL doesn't have Otsu natively, so we use a simple threshold.
    """
    arr = np.array(img)
    threshold = int(arr.mean() * 0.9)         
    binary = Image.fromarray((arr > threshold).astype(np.uint8) * 255)
    return binary


def _deskew(img: Image.Image) -> Image.Image:
    """
    Detect and correct document skew using projection profile analysis.
    Returns corrected image.
    """
    try:
        arr = np.array(img)
        best_angle = 0.0
        best_score = -1.0

        for angle in np.arange(-10, 10, 0.5):
            rotated = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
            rot_arr = np.array(rotated)
            profile = rot_arr.sum(axis=1).astype(float)
            score = float(profile.var())
            if score > best_score:
                best_score = score
                best_angle = angle

        if abs(best_angle) > 0.3:
            logger.debug("Deskewing by %.1f°", best_angle)
            return img.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    except Exception as exc:
        logger.warning("Deskew failed: %s", exc)

    return img


def _scale_up(img: Image.Image, min_dpi_equivalent: int = 200) -> Image.Image:
    """
    If the image is very small (e.g. thumbnail-sized), scale up before OCR.
    Tesseract works best at ~300 DPI equivalent (~2480px wide for A4).
    """
    w, h = img.size
    if w < 1000:
        scale = 1500 / w
        new_w = int(w * scale)
        new_h = int(h * scale)
        return img.resize((new_w, new_h), Image.LANCZOS)
    return img


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Full preprocessing pipeline for a page image."""
    img = _scale_up(img)
    img = _to_grayscale(img)
    img = _denoise(img)
    img = _enhance_contrast(img)
    img = _deskew(img)
    img = _sharpen(img)
    return img


# ── OCR execution ────────────────────────────────────────────────────────────

def _run_tesseract(img: Image.Image) -> Tuple[str, float]:
    """
    Run Tesseract on a preprocessed PIL image.
    Returns (raw_text, avg_confidence).
    Confidence is the mean of per-word confidences (0–100 → 0.0–1.0).
    """
    try:
        # Get per-word confidence data
        data = pytesseract.image_to_data(
            img,
            lang=TESSERACT_LANG,
            config=TESSERACT_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        words      = [w for w in data["text"]   if w.strip()]
        conf_vals  = [
            c for c, w in zip(data["conf"], data["text"])
            if w.strip() and c >= 0   # -1 means Tesseract skipped
        ]
        raw_text   = pytesseract.image_to_string(
            img, lang=TESSERACT_LANG, config=TESSERACT_CONFIG
        )
        avg_conf = (sum(conf_vals) / len(conf_vals) / 100.0) if conf_vals else 0.0
        return raw_text, round(avg_conf, 3)

    except Exception as exc:
        logger.error("Tesseract error: %s", exc)
        return "", 0.0


def ocr_image_file(image_path: Path, page_number: int = 1) -> PageResult:
    """OCR a standalone image file (PNG, JPG, TIFF, etc.)."""
    img = Image.open(image_path)
    if img.mode == "RGBA":
        # Flatten alpha on white background
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background

    preprocessed = preprocess_for_ocr(img)
    raw_text, confidence = _run_tesseract(preprocessed)
    cleaned_text, warnings = clean_text(raw_text)

    if confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Low OCR confidence ({confidence:.0%}) — text may be inaccurate"
        )

    return PageResult(
        page_number=page_number,
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        confidence=confidence,
        extraction_method=ExtractionMethod.OCR_IMAGE,
        word_count=len(cleaned_text.split()),
        warnings=warnings,
    )


def ocr_pil_image(img: Image.Image, page_number: int) -> PageResult:
    """OCR a PIL Image object (used when PDF page is converted to image)."""
    preprocessed = preprocess_for_ocr(img)
    raw_text, confidence = _run_tesseract(preprocessed)
    cleaned_text, warnings = clean_text(raw_text)

    if confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Page {page_number}: low OCR confidence ({confidence:.0%})"
        )

    return PageResult(
        page_number=page_number,
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        confidence=confidence,
        extraction_method=ExtractionMethod.OCR_SCAN,
        word_count=len(cleaned_text.split()),
        warnings=warnings,
    )
