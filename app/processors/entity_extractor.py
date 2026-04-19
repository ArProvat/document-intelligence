import re
from typing import List, Tuple

from app.models.schemas import ExtractedEntity, PageResult

# ── Regex patterns ────────────────────────────────────────────────────────────

_DATE_PATTERNS = [
    r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b',                          # 12/31/2024
    r'\b(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})\b',                            # 2024-12-31
    r'\b(\w+ \d{1,2},\s*\d{4})\b',                                        # December 31, 2024
    r'\b(\d{1,2}(?:st|nd|rd|th)? (?:day of )?\w+ \d{4})\b',              # 31st day of December 2024
    r'\b(\d{1,2} \w+ \d{4})\b',                                           # 31 December 2024
]

_AMOUNT_PATTERNS = [
    r'\$\s*[\d,]+(?:\.\d{2})?',            # $1,200.00
    r'USD\s*[\d,]+(?:\.\d{2})?',           # USD 1200
    r'[\d,]+(?:\.\d{2})?\s*dollars?',      # 1,200.00 dollars
]

_CASE_NUMBER_PATTERNS = [
    r'(?:Case\s*(?:No\.?|Number)\s*[:.]?\s*)([\w\-/]+)',
    r'(?:Docket\s*(?:No\.?|#)\s*[:.]?\s*)([\w\-/]+)',
    r'\b(\d{2}-[A-Z]{2}-\d{4,6})\b',       # 24-CV-001234
    r'\b([A-Z]{2}\s*\d{4,8})\b',
]

_PARTY_TRIGGERS = [
    r'(?:between|by and between)\s+([A-Z][A-Za-z ,.\'-]{3,60}?)\s+(?:and|,)',
    r'(?:Plaintiff|Petitioner)[,:]?\s+([A-Z][A-Za-z ,.\'-]{3,60})',
    r'(?:Defendant|Respondent)[,:]?\s+([A-Z][A-Za-z ,.\'-]{3,60})',
    r'(?:Landlord|Lessor)[,:]?\s+([A-Z][A-Za-z ,.\'-]{3,60})',
    r'(?:Tenant|Lessee)[,:]?\s+([A-Z][A-Za-z ,.\'-]{3,60})',
    r'(?:Grantor|Grantee)[,:]?\s+([A-Z][A-Za-z ,.\'-]{3,60})',
]

_ADDRESS_PATTERN = (
    r'\d{1,5}\s+\w[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd'
    r'|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Way|Circle|Cir)'
    r'(?:\.)?(?:\s+(?:Suite|Ste|Apt|Unit|#)\s*[\w\d]+)?'
    r'(?:,\s*[\w\s]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?'
)


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_date(raw: str) -> str:
    """Best-effort: return raw date as-is (full NLP parser not required)."""
    return raw.strip()


def _normalize_amount(raw: str) -> str:
    digits = re.sub(r'[^\d.]', '', raw)
    try:
        return f"${float(digits):,.2f}"
    except ValueError:
        return raw


# ── Extraction ────────────────────────────────────────────────────────────────

def _extract_with_patterns(
    text: str, patterns: List[str], entity_type: str, page: int, confidence: float
) -> List[ExtractedEntity]:
    entities = []
    seen = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            value = (m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)).strip()
            if value and value not in seen:
                seen.add(value)
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    value=value,
                    normalized=None,
                    page=page,
                    confidence=confidence,
                ))
    return entities


def extract_entities(pages: List[PageResult]) -> List[ExtractedEntity]:
    """
    Extract structured entities from all page results.
    Returns a deduplicated list of ExtractedEntity objects.
    """
    all_entities: List[ExtractedEntity] = []
    global_seen: dict[str, bool] = {}

    for page in pages:
        text = page.cleaned_text
        if not text:
            continue
        pg = page.page_number
        conf = page.confidence

        # Dates
        for ent in _extract_with_patterns(text, _DATE_PATTERNS, "date", pg, conf):
            ent.normalized = _normalize_date(ent.value)
            key = f"date::{ent.value}"
            if key not in global_seen:
                global_seen[key] = True
                all_entities.append(ent)

        # Monetary amounts
        for ent in _extract_with_patterns(text, _AMOUNT_PATTERNS, "amount", pg, conf):
            ent.normalized = _normalize_amount(ent.value)
            key = f"amount::{ent.normalized}"
            if key not in global_seen:
                global_seen[key] = True
                all_entities.append(ent)

        # Case numbers
        for ent in _extract_with_patterns(text, _CASE_NUMBER_PATTERNS, "case_number", pg, conf):
            key = f"case_number::{ent.value}"
            if key not in global_seen:
                global_seen[key] = True
                all_entities.append(ent)

        # Parties
        for ent in _extract_with_patterns(text, _PARTY_TRIGGERS, "party", pg, conf):
            # Filter out short / generic matches
            if len(ent.value) > 4 and not ent.value.lower().startswith("the "):
                key = f"party::{ent.value.lower()}"
                if key not in global_seen:
                    global_seen[key] = True
                    all_entities.append(ent)

        # Addresses
        for m in re.finditer(_ADDRESS_PATTERN, text, re.IGNORECASE):
            addr = m.group(0).strip()
            key = f"address::{addr.lower()}"
            if key not in global_seen and len(addr) > 10:
                global_seen[key] = True
                all_entities.append(ExtractedEntity(
                    entity_type="address",
                    value=addr,
                    normalized=addr,
                    page=pg,
                    confidence=conf,
                ))

    return all_entities
