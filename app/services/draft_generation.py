from datetime import datetime, timezone
from typing import List

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.models.api_schemas import DraftType, EvidenceItem, DraftResponse
from app.retrieval.hybrid_search import HybridSessionRetriever


DRAFT_TYPE_GUIDANCE = {
    DraftType.TITLE_REVIEW_SUMMARY: (
        "Focus on ownership, deed history, grantor/grantee, liens, easements, "
        "mortgages, encumbrances, property description, and missing title documents."
    ),
    DraftType.CASE_FACT_SUMMARY: (
        "Focus on parties, timeline, factual events, case numbers, allegations, "
        "procedural posture, and inconsistencies across documents."
    ),
    DraftType.NOTICE_RELATED_SUMMARY: (
        "Focus on notice type, issuing party, recipient, dates, deadlines, "
        "default/cure language, service details, and obligations triggered."
    ),
    DraftType.DOCUMENT_CHECKLIST: (
        "Focus on what document types are present, what appears missing, "
        "duplicates, low-confidence scans, and documents requiring manual review."
    ),
    DraftType.INTERNAL_MEMO: (
        "Focus on key facts, important risks, unresolved questions, missing evidence, "
        "and a concise internal first-pass memo structure."
    ),
}


class DraftGenerationService:
    def __init__(self, retriever: HybridSessionRetriever):
        self.retriever = retriever

        self.query_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
        )
        self.draft_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.2,
        )

        self.query_prompt = ChatPromptTemplate.from_template(
            """
You are a retrieval query writer for legal-style document drafting.

Task type:
{draft_type}

Task guidance:
{draft_guidance}

Operator instructions:
{instructions}

Rewrite the request into a retrieval-oriented search query.
The query should help retrieve the most relevant document chunks from the session.
Prefer concrete entities, legal events, exact phrases, and document features.

Return only the search query.
"""
        )

        self.draft_prompt = ChatPromptTemplate.from_template(
            """
You are generating a grounded first-pass legal-style draft.

Task type:
{draft_type}

Task guidance:
{draft_guidance}

Operator instructions:
{instructions}

Rules:
- Use only the evidence below.
- Do not invent facts.
- If information is missing, unclear, or conflicting, say so explicitly.
- Keep the draft useful as a first pass.
- Base important statements on the retrieved evidence.

Evidence:
{evidence}

Write the draft now.
"""
        )

        self.query_chain = self.query_prompt | self.query_llm | StrOutputParser()
        self.draft_chain = self.draft_prompt | self.draft_llm | StrOutputParser()

    def _format_evidence(self, docs: List[Document]) -> str:
        blocks = []
        for i, doc in enumerate(docs, start=1):
            meta = doc.metadata or {}
            blocks.append(
                "\n".join(
                    [
                        f"[Evidence {i}]",
                        f"filename: {meta.get('filename', '')}",
                        f"doc_id: {meta.get('doc_id', '')}",
                        f"chunk_id: {meta.get('chunk_id', '')}",
                        f"pages: {meta.get('page_start', '')}-{meta.get('page_end', '')}",
                        f"doc_type: {meta.get('doc_type', '')}",
                        f"text: {doc.page_content}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def generate_draft(
        self,
        session_id: str,
        draft_type: DraftType,
        instructions: str | None = None,
    ) -> DraftResponse:
        guidance = DRAFT_TYPE_GUIDANCE[draft_type]

        retrieval_query = self.query_chain.invoke(
            {
                "draft_type": draft_type.value,
                "draft_guidance": guidance,
                "instructions": instructions or "None",
            }
        )

        rerank_retriever = self.retriever.rerank_retriever(session_id)
        docs = rerank_retriever.invoke(retrieval_query)

        evidence_text = self._format_evidence(docs)

        draft = self.draft_chain.invoke(
            {
                "draft_type": draft_type.value,
                "draft_guidance": guidance,
                "instructions": instructions or "None",
                "evidence": evidence_text,
            }
        )

        evidence_items = []
        for d in docs:
            meta = d.metadata or {}
            evidence_items.append(
                EvidenceItem(
                    doc_id=meta.get("doc_id", ""),
                    filename=meta.get("filename", ""),
                    chunk_id=meta.get("chunk_id", ""),
                    page_start=meta.get("page_start", 1),
                    page_end=meta.get("page_end", 1),
                    snippet=d.page_content[:500],
                )
            )

        return DraftResponse(
            session_id=session_id,
            draft_type=draft_type,
            retrieval_query=retrieval_query,
            draft=draft,
            evidence=evidence_items,
            generated_at=datetime.now(timezone.utc),
        )