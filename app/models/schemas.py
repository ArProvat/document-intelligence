from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    LEASE_AGREEMENT = "lease_agreement"
    COURT_FILING = "court_filing"
    LEGAL_NOTICE = "legal_notice"
    INTERNAL_MEMO = "internal_memo"
    CONTRACT = "contract"
    TITLE_DOCUMENT = "title_document"
    CORRESPONDENCE = "correspondence"
    UNKNOWN = "unknown"


class ExtractionMethod(str, Enum):
    NATIVE_TEXT = "native_text"
    OCR_SCAN = "ocr_scan"
    OCR_IMAGE = "ocr_image"
    MULTIMODAL_LLM = "multimodal_llm"
    HYBRID = "hybrid"


class PageResult(BaseModel):
    page_number: int
    raw_text: str
    cleaned_text: str
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence from 0.0 to 1.0")
    extraction_method: ExtractionMethod
    word_count: int
    has_tables: bool = False
    tables: List[List[List[str]]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    entity_type: str
    value: str
    normalized: Optional[str] = None
    page: int
    confidence: float


class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    chunk_index: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProcessingWarning(BaseModel):
    code: str
    message: str
    page: Optional[int] = None


class ProcessedDocument(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    processed_at: datetime
    doc_type: DocumentType
    doc_type_confidence: float
    extraction_method: ExtractionMethod
    total_pages: int
    avg_confidence: float
    low_confidence_pages: List[int] = Field(default_factory=list)
    full_text: str
    pages: List[PageResult]
    entities: List[ExtractedEntity] = Field(default_factory=list)
    chunks: List[DocumentChunk] = Field(default_factory=list)
    warnings: List[ProcessingWarning] = Field(default_factory=list)
    is_usable: bool = True
    quality_score: float = Field(..., ge=0.0, le=1.0)


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    status: str
    message: str
    processing_time_seconds: float
    quality_score: float
    doc_type: str
    total_pages: int
    avg_confidence: float
    chunk_count: int
    entity_count: int
    warnings: List[str] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    total_pages: int
    quality_score: float
    avg_confidence: float
    processed_at: datetime
    is_usable: bool
    chunk_count: int
