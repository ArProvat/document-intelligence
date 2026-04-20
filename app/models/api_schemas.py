from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.schemas import UploadResponse


class DraftType(str, Enum):
    TITLE_REVIEW_SUMMARY = "title_review_summary"
    CASE_FACT_SUMMARY = "case_fact_summary"
    NOTICE_RELATED_SUMMARY = "notice_related_summary"
    DOCUMENT_CHECKLIST = "document_checklist"
    INTERNAL_MEMO = "internal_memo"


class StyleRuleCategory(str, Enum):
    STRUCTURE = "structure"
    TONE = "tone"
    COMPLETENESS = "completeness"
    CITATION_STYLE = "citation_style"
    FORMATTING = "formatting"
    ANALYSIS = "analysis"
    OTHER = "other"


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


class AppliedStyleRule(BaseModel):
    rule_id: str
    description: str
    category: StyleRuleCategory
    confidence: float


class StyleRule(BaseModel):
    rule_id: str
    description: str
    category: StyleRuleCategory
    example_before: str
    example_after: str
    applicable_draft_types: List[DraftType] = Field(default_factory=list)
    confidence: float
    support_count: int = 1
    last_updated: datetime


class DraftResponse(BaseModel):
    draft_id: str
    session_id: str
    draft_type: DraftType
    retrieval_query: str
    draft: str
    evidence: List[EvidenceItem]
    applied_rules: List[AppliedStyleRule] = Field(default_factory=list)
    generated_at: datetime


class StructuredDiffEntry(BaseModel):
    operation: str
    before: str = ""
    after: str = ""


class DraftFeedbackRequest(BaseModel):
    edited_draft: str
    operator_notes: Optional[str] = Field(
        default=None,
        description="Optional operator note, e.g. always cite section numbers",
    )


class DraftFeedbackResponse(BaseModel):
    feedback_id: str
    draft_id: str
    extracted_rules: List[StyleRule] = Field(default_factory=list)
    active_rules: List[StyleRule] = Field(default_factory=list)
    structured_diff: List[StructuredDiffEntry] = Field(default_factory=list)
