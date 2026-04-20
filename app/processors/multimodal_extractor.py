import base64
import io
import logging

from openai import OpenAI
from PIL import Image

from config import (
    MULTIMODAL_FALLBACK_DETAIL,
    MULTIMODAL_FALLBACK_ENABLED,
    MULTIMODAL_FALLBACK_MAX_IMAGE_EDGE,
    MULTIMODAL_FALLBACK_MIN_TEXT_LENGTH,
    MULTIMODAL_FALLBACK_MODEL,
    OCR_CONFIDENCE_THRESHOLD,
)
from app.models.schemas import ExtractionMethod, PageResult
from app.processors.text_cleaner import clean_text, estimate_confidence_from_text

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client

    if _client is None:
        _client = OpenAI()

    return _client


def _prepare_image(image: Image.Image) -> Image.Image:
    working = image.convert("RGB")
    max_edge = max(working.size)

    if max_edge <= MULTIMODAL_FALLBACK_MAX_IMAGE_EDGE:
        return working

    scale = MULTIMODAL_FALLBACK_MAX_IMAGE_EDGE / max_edge
    resized = (
        max(1, int(working.size[0] * scale)),
        max(1, int(working.size[1] * scale)),
    )
    return working.resize(resized, Image.LANCZOS)


def _image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _should_use_fallback(page_result: PageResult) -> bool:
    if not MULTIMODAL_FALLBACK_ENABLED:
        return False

    if not page_result.cleaned_text.strip():
        return True

    if page_result.confidence < OCR_CONFIDENCE_THRESHOLD:
        return True

    return len(page_result.cleaned_text.strip()) < MULTIMODAL_FALLBACK_MIN_TEXT_LENGTH


def _extract_with_multimodal_model(image: Image.Image, source_label: str) -> tuple[str, float, list[str]]:
    if not MULTIMODAL_FALLBACK_ENABLED:
        return "", 0.0, []

    prompt = (
        "Transcribe all legible text from this document image. "
        "This may include handwriting, faint scans, stamps, form labels, tables, or low-quality text. "
        "Return only extracted text in reading order. "
        "Preserve line breaks where meaningful. "
        "For tables, keep rows on separate lines and separate cells with ' | '. "
        "If a word is unclear, provide your best guess followed by '[?]'. "
        "Do not summarize, explain, or add commentary."
    )

    prepared = _prepare_image(image)
    data_url = _image_to_data_url(prepared)

    try:
        response = _get_client().responses.create(
            model=MULTIMODAL_FALLBACK_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": data_url,
                            "detail": MULTIMODAL_FALLBACK_DETAIL,
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        logger.warning("Multimodal fallback failed for %s: %s", source_label, exc)
        return "", 0.0, [f"Multimodal fallback failed: {exc}"]

    raw_text = (response.output_text or "").strip()
    cleaned_text, warnings = clean_text(raw_text)
    confidence = estimate_confidence_from_text(raw_text, cleaned_text)

    if not cleaned_text:
        warnings.append("Multimodal fallback returned no usable text")

    return raw_text, confidence, warnings


def maybe_apply_multimodal_fallback(
    image: Image.Image,
    page_result: PageResult,
    source_label: str,
) -> PageResult:
    if not _should_use_fallback(page_result):
        return page_result

    original_text_len = len(page_result.cleaned_text.strip())
    original_confidence = page_result.confidence
    raw_text, fallback_confidence, fallback_warnings = _extract_with_multimodal_model(
        image=image,
        source_label=source_label,
    )
    fallback_cleaned, _ = clean_text(raw_text)

    if not fallback_cleaned:
        page_result.warnings.extend(fallback_warnings)
        return page_result

    should_replace = (
        len(fallback_cleaned.strip()) > original_text_len
        or fallback_confidence > original_confidence
        or not page_result.cleaned_text.strip()
    )

    if should_replace:
        page_result.raw_text = raw_text
        page_result.cleaned_text = fallback_cleaned
        page_result.confidence = max(original_confidence, fallback_confidence)
        page_result.word_count = len(page_result.cleaned_text.split())
        page_result.extraction_method = ExtractionMethod.MULTIMODAL_LLM
        page_result.warnings.append(
            "Used multimodal LLM fallback because OCR was empty, low-confidence, or too short"
        )
        page_result.warnings.extend(fallback_warnings)
        return page_result

    page_result.warnings.append(
        "Multimodal LLM fallback was attempted, but the original OCR output was retained"
    )
    page_result.warnings.extend(fallback_warnings)
    return page_result
