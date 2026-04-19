import re
import unicodedata
from typing import Tuple


# ── Common OCR substitution errors ──────────────────────────────────────────
_OCR_FIXES: list[Tuple[str, str]] = [
    (r'\bl\b',   'I'),          # lone lowercase L → capital I (common Tesseract error)
    (r'\b0\b',   'O'),          # lone zero → O in pure-word context (handled carefully)
    (r'rn',      'm'),          # 'rn' misread as 'm' predecessor
    (r'\|',      'I'),          # pipe char misread for capital I
    (r'(?<=[a-z])-\n(?=[a-z])', ''),   # fix mid-word hyphen line breaks → rejoin
    (r'(?<!\n)\n(?!\n)',        ' '),   # single newline (not paragraph) → space
    (r'\n{3,}',                 '\n\n'),# collapse 3+ blank lines to 2
    (r'[ \t]{2,}',              ' '),   # collapse multiple spaces/tabs
    (r'([a-z])- ([A-Z])',       r'\1-\2'),  # hyphen split across sentences
]

# ── Patterns to strip entirely ───────────────────────────────────────────────
_NOISE_PATTERNS = [
    r'^\s*[_\-=]{4,}\s*$',          # horizontal rules (_____, -----)
    r'^\s*\f\s*$',                   # form-feed characters alone on a line
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]',  # control characters
]


def normalize_unicode(text: str) -> str:
    """Normalize Unicode to NFC and replace common lookalike characters."""
    text = unicodedata.normalize("NFC", text)
    # Replace fancy quotes / dashes with ASCII equivalents
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '--', '\u2026': '...',
        '\u00a0': ' ',   # non-breaking space
        '\u00ad': '',    # soft hyphen
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def strip_noise(text: str) -> str:
    """Remove lines that are purely OCR noise artifacts."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        skip = any(re.match(p, line) for p in _NOISE_PATTERNS)
        if not skip:
            cleaned.append(line)
    return '\n'.join(cleaned)


def fix_ocr_errors(text: str) -> str:
    """Apply conservative OCR error corrections."""
    for pattern, replacement in _OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def fix_spacing_around_punctuation(text: str) -> str:
    """Ensure no space before punctuation, single space after."""
    text = re.sub(r'\s+([.,;:!?)\]])',  r'\1',    text)   # space BEFORE punct
    text = re.sub(r'([.,;:!?)\]])\s+', r'\1 ',    text)   # ensure space AFTER punct
    text = re.sub(r'\(\s+',            '(',        text)   # space after (
    text = re.sub(r'\s+\)',            ')',         text)   # space before )
    return text


def normalize_legal_abbreviations(text: str) -> str:
    """Preserve common legal abbreviations that OCR sometimes splits."""
    abbreviations = [
        (r'v \.',   'v.'),     # versus
        (r'et al \.',  'et al.'),
        (r'e \. g \.',  'e.g.'),
        (r'i \. e \.',  'i.e.'),
        (r'No \.',  'No.'),
        (r'Sec \.',  'Sec.'),
        (r'Art \.',  'Art.'),
    ]
    for pattern, replacement in abbreviations:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def clean_text(raw_text: str) -> Tuple[str, list[str]]:
    """
    Full cleaning pipeline.
    Returns (cleaned_text, list_of_warnings).
    """
    warnings = []

    if not raw_text or not raw_text.strip():
        return "", ["Empty or blank text — no content extracted"]

    text = normalize_unicode(raw_text)
    text = strip_noise(text)
    text = fix_ocr_errors(text)
    text = fix_spacing_around_punctuation(text)
    text = normalize_legal_abbreviations(text)

    # Final pass: collapse trailing whitespace per line
    lines = [line.rstrip() for line in text.splitlines()]
    text = '\n'.join(lines).strip()

    # Quality warnings
    if len(text) < 50:
        warnings.append("Very little text extracted — page may be blank or image-only")

    # Detect likely garbled OCR (high ratio of non-alphabetic chars)
    alpha_ratio = sum(c.isalpha() for c in text) / max(len(text), 1)
    if alpha_ratio < 0.4:
        warnings.append(
            f"Low alpha ratio ({alpha_ratio:.0%}) — output may contain OCR noise"
        )

    # Detect if text looks like all uppercase (common scan artifact)
    upper_ratio = sum(c.isupper() for c in text if c.isalpha()) / max(
        sum(c.isalpha() for c in text), 1
    )
    if upper_ratio > 0.85 and len(text) > 100:
        warnings.append("Text is mostly uppercase — may be a stylistic choice or OCR issue")

    return text, warnings


def estimate_confidence_from_text(raw: str, cleaned: str) -> float:
    """
    Heuristic confidence when Tesseract per-word data is unavailable.
    Based on character quality of the extracted text.
    """
    if not cleaned:
        return 0.0

    alpha_ratio  = sum(c.isalpha() for c in cleaned) / max(len(cleaned), 1)
    space_ratio  = sum(c == ' '    for c in cleaned) / max(len(cleaned), 1)
    punct_ok     = 0.1 < space_ratio < 0.25

    score = alpha_ratio * 0.6 + (0.4 if punct_ok else 0.0)
    return round(min(max(score, 0.0), 1.0), 3)
