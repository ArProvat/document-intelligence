import logging
from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

from config import (
    MIN_TEXT_LENGTH_PER_PAGE,
    OCR_CONFIDENCE_THRESHOLD,
    TESSERACT_CONFIG,
    TESSERACT_LANG,
)
from app.models.schemas import ExtractionMethod, PageResult
from app.processors.multimodal_extractor import maybe_apply_multimodal_fallback
from app.processors.text_cleaner import clean_text

logger = logging.getLogger(__name__)


def _to_grayscale(img: Image.Image) -> Image.Image:
    return img.convert("L")


def _denoise(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius=0.5))


def _enhance_contrast(img: Image.Image) -> Image.Image:
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(2.0)


def _sharpen(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))


def _deskew(img: Image.Image) -> Image.Image:
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
            logger.debug("Deskewing by %.1f degrees", best_angle)
            return img.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    except Exception as exc:
        logger.warning("Deskew failed: %s", exc)

    return img


def _scale_up(img: Image.Image) -> Image.Image:
    width, height = img.size
    if width < 1000:
        scale = 1500 / width
        return img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    return img


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img = _scale_up(img)
    img = _to_grayscale(img)
    img = _denoise(img)
    img = _enhance_contrast(img)
    img = _deskew(img)
    img = _sharpen(img)
    return img


def _flatten_image(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        return background

    if img.mode != "RGB":
        return img.convert("RGB")

    return img


def _run_tesseract(img: Image.Image) -> Tuple[str, float]:
    try:
        data = pytesseract.image_to_data(
            img,
            lang=TESSERACT_LANG,
            config=TESSERACT_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        conf_vals = [
            confidence
            for confidence, text in zip(data["conf"], data["text"])
            if text.strip() and confidence >= 0
        ]
        raw_text = pytesseract.image_to_string(
            img,
            lang=TESSERACT_LANG,
            config=TESSERACT_CONFIG,
        )
        avg_conf = (sum(conf_vals) / len(conf_vals) / 100.0) if conf_vals else 0.0
        return raw_text, round(avg_conf, 3)
    except Exception as exc:
        logger.error("Tesseract error: %s", exc)
        return "", 0.0


def _extract_page_result(
    img: Image.Image,
    page_number: int,
    extraction_method: ExtractionMethod,
    low_confidence_warning: str,
    source_label: str,
) -> PageResult:
    base_image = _flatten_image(img)
    raw_text, confidence = _run_tesseract(preprocess_for_ocr(base_image))
    cleaned_text, warnings = clean_text(raw_text)

    if confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(low_confidence_warning.format(confidence=confidence))

    page_result = PageResult(
        page_number=page_number,
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        confidence=confidence,
        extraction_method=extraction_method,
        word_count=len(cleaned_text.split()),
        warnings=warnings,
    )

    if confidence < OCR_CONFIDENCE_THRESHOLD or len(cleaned_text.strip()) < MIN_TEXT_LENGTH_PER_PAGE:
        page_result = maybe_apply_multimodal_fallback(
            image=base_image,
            page_result=page_result,
            source_label=source_label,
        )

    return page_result


def ocr_image_file(image_path: Path, page_number: int = 1) -> PageResult:
    img = Image.open(image_path)
    return _extract_page_result(
        img=img,
        page_number=page_number,
        extraction_method=ExtractionMethod.OCR_IMAGE,
        low_confidence_warning="Low OCR confidence ({confidence:.0%}) - text may be inaccurate",
        source_label=f"image file page {page_number}",
    )


def ocr_pil_image(img: Image.Image, page_number: int) -> PageResult:
    return _extract_page_result(
        img=img,
        page_number=page_number,
        extraction_method=ExtractionMethod.OCR_SCAN,
        low_confidence_warning=f"Page {page_number}: low OCR confidence ({{confidence:.0%}})",
        source_label=f"pdf page {page_number}",
    )
