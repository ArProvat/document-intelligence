from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class DocumentType(str, Enum):
    LEASE_AGREEMENT   = "lease_agreement"
    COURT_FILING      = "court_filing"
    LEGAL_NOTICE      = "legal_notice"
    INTERNAL_MEMO     = "internal_memo"
    CONTRACT          = "contract"
    TITLE_DOCUMENT    = "title_document"
    CORRESPONDENCE    = "correspondence"
    UNKNOWN           = "unknown"


class ExtractionMethod(str, Enum):
    NATIVE_TEXT = "native_text"   # PDF has real text layer
    OCR_SCAN    = "ocr_scan"      # Scanned — OCR applied
    OCR_IMAGE   = "ocr_image"     # Standalone image file
    HYBRID      = "hybrid"        # Mixed: some pages native, some OCR
