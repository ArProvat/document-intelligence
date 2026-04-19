import re
from typing import Tuple, Dict, List

from app.models.schemas import DocumentType

# ── Keyword sets per document type ───────────────────────────────────────────
# Each entry: (DocumentType, weight, [keywords])
_RULES: List[Tuple[DocumentType, float, List[str]]] = [
    (DocumentType.LEASE_AGREEMENT, 1.5, [
        "lease", "tenant", "landlord", "lessor", "lessee",
        "monthly rent", "premises", "security deposit",
        "term of lease", "tenancy", "rent due", "sq ft", "square feet",
        "possession", "notice to quit",
    ]),
    (DocumentType.COURT_FILING, 1.5, [
        "plaintiff", "defendant", "petitioner", "respondent",
        "case no", "case number", "docket", "court of",
        "superior court", "district court", "complaint",
        "motion", "affidavit", "declaration", "hereby ordered",
        "judgment", "verdict", "summons", "subpoena", "deposition",
    ]),
    (DocumentType.LEGAL_NOTICE, 1.2, [
        "notice", "hereby notified", "pursuant to",
        "demand", "default", "cure or quit",
        "notice of termination", "notice of default",
        "you are hereby", "within days",
    ]),
    (DocumentType.INTERNAL_MEMO, 1.0, [
        "memorandum", "memo", "to:", "from:", "re:", "subject:",
        "date:", "internal", "confidential",
        "please note", "please be advised", "as discussed",
        "action required", "for your review",
    ]),
    (DocumentType.CONTRACT, 1.3, [
        "agreement", "contract", "parties", "whereas",
        "consideration", "terms and conditions",
        "in witness whereof", "executed", "binding",
        "effective date", "obligations", "representations",
        "warranties", "indemnification", "governing law",
    ]),
    (DocumentType.TITLE_DOCUMENT, 1.4, [
        "title", "deed", "grantor", "grantee", "convey",
        "property description", "metes and bounds",
        "parcel", "lot number", "assessor", "encumbrance",
        "lien", "easement", "chain of title", "abstract",
    ]),
    (DocumentType.CORRESPONDENCE, 0.9, [
        "dear", "sincerely", "yours truly", "regards",
        "please find", "enclosed", "attached",
        "in response to", "thank you for",
        "i am writing", "we are writing", "please contact",
    ]),
]


def classify_document(full_text: str) -> Tuple[DocumentType, float]:
    """
    Score each document type against the extracted text using weighted keyword matching.
    Returns (best_type, confidence_0_to_1).
    """
    if not full_text or not full_text.strip():
        return DocumentType.UNKNOWN, 0.0

    text_lower = full_text.lower()
    scores: Dict[DocumentType, float] = {}

    for doc_type, weight, keywords in _RULES:
        hits = sum(
            len(re.findall(r'\b' + re.escape(kw) + r'\b', text_lower))
            for kw in keywords
        )
        scores[doc_type] = hits * weight

    best_type  = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score == 0:
        return DocumentType.UNKNOWN, 0.0

    total = sum(scores.values())
    confidence = round(min(best_score / max(total, 1) * 1.5, 1.0), 3)

    return best_type, confidence
