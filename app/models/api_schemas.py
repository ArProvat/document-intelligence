from enum import Enum
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.schemas import UploadResponse


class DraftType(str, Enum):
    TITLE_REVIEW_SUMMARY = "title_review_summary"
    CASE_FACT_SUMMARY = "case_fact_summary"
    NOTICE_RELATED_SUMMARY = "notice_related_summary"
    DOCUMENT_CHECKLIST = "document_checklist"
    INTERNAL_MEMO = "internal_memo"


class CreateSessionRequest(BaseModel):
    user_id: str = Field(..., description="Application user ID")


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: datetime
    document_ids: List[str] = Field(default_factory=list)


class SessionUploadResponse(BaseModel):
    session_id: str
    uploaded_count: int
    documents: List[UploadResponse]


class DraftRequest(BaseModel):
    draft_type: DraftType
    instructions: Optional[str] = Field(
        default=None,
        description="Optional operator instruction, e.g. emphasize timeline or missing docs",
    )


class EvidenceItem(BaseModel):
    doc_id: str
    filename: str
    chunk_id: str
    page_start: int
    page_end: int
    snippet: str


class DraftResponse(BaseModel):
    session_id: str
    draft_type: DraftType
    retrieval_query: str
    draft: str
    evidence: List[EvidenceItem]
    generated_at: datetime