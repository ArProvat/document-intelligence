import logging
import time
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.documents import Document as LCDocument

from app.config import OPENAI_CHAT_MODEL
from app.models.session_schemas import DraftRequest, DraftResponse, EvidenceChunk
from app.models.retrieval_schemas import SearchFilters, SearchRequest
from app.retrieval.retrieval_service import search

logger = logging.getLogger(__name__)


_DRAFT_PROMPTS: dict[str, str] = {
    "case_fact_summary": """\
You are a legal analyst at Pearson Specter Litt. Draft a structured CASE FACT SUMMARY with:
1. Parties — all plaintiffs, defendants, and counsel
2. Key Dates — chronological list of material dates
3. Core Facts — numbered factual statements only
4. Claims / Causes of Action — what is alleged
5. Relief Sought — damages or other remedies
6. Open Issues — gaps or unclear facts in the source""",

    "title_review_summary": """\
You are a real estate attorney at Pearson Specter Litt. Draft a TITLE REVIEW SUMMARY with:
1. Property Description — address, parcel, legal description
2. Current Owner / Grantor
3. Chain of Title — key conveyances in chronological order
4. Encumbrances — liens, mortgages, easements, covenants
5. Title Issues / Exceptions
6. Recommended Actions""",

    "notice_summary": """\
You are a legal analyst at Pearson Specter Litt. Draft a NOTICE SUMMARY with:
1. Notice Type
2. Issuing Party and authority
3. Recipient
4. Default / Breach — what obligation was violated
5. Amount Owed (exact figures)
6. Cure Period and deadline
7. Consequences of Non-Compliance
8. Statutory Basis — cite statutes referenced in the documents""",

    "document_checklist": """\
You are a legal analyst at Pearson Specter Litt. Generate a DOCUMENT CHECKLIST.
For each source document: name/type, date, parties, key obligations, status (complete/incomplete/unclear).
List any documents referenced but missing from the source materials.""",

    "internal_memo": """\
You are a senior associate at Pearson Specter Litt. Write an INTERNAL MEMO:
TO: [Supervising Partner]
FROM: [Associate]
DATE: [Today]
RE: [Subject derived from documents]
---
EXECUTIVE SUMMARY (2-3 sentences)
BACKGROUND
KEY FINDINGS
RISKS / ISSUES IDENTIFIED
RECOMMENDED NEXT STEPS""",

    "custom": "You are a legal analyst at Pearson Specter Litt. Follow the instruction precisely. Produce a well-structured professional legal document.",
}

_GROUNDING_RULE = """\
CRITICAL GROUNDING RULES — FOLLOW EXACTLY:
- Use ONLY the evidence chunks below as your source.
- After every factual claim, add a citation: [Doc: {filename}, p.{page}]
- If information is NOT in the evidence, write [NOT IN SOURCE DOCUMENTS] — never invent facts.
- If evidence is contradictory, state the contradiction explicitly.
- Do not add legal advice beyond what the evidence supports."""

# ── LCEL prompt template ───────────────────────────────────────────────────────

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_instruction}\n\n{grounding_rule}"),
    ("human",  "{evidence_block}\n\n=== USER INSTRUCTION ===\n{instruction}\n\nNow produce the draft with inline citations."),
])


def _format_evidence(docs: List[LCDocument]) -> str:
    lines = ["=== EVIDENCE CHUNKS ===\n"]
    for i, doc in enumerate(docs, 1):
        meta  = doc.metadata
        fname = meta.get("filename", "unknown")
        p_s   = meta.get("page_start", "?")
        p_e   = meta.get("page_end",   "?")
        page  = f"p.{p_s}" if p_s == p_e else f"p.{p_s}-{p_e}"
        score = meta.get("relevance_score", "")
        score_str = f" | score={float(score):.3f}" if score else ""
        lines.append(f"[{i}] {fname} | {page}{score_str}\n{doc.page_content}\n")
    return "\n".join(lines)


def generate_draft(
    session_id: str,
    req: DraftRequest,
    session_doc_ids: List[str],
) -> DraftResponse:
    """Build LCEL chain and generate a grounded draft for the session."""
    t0 = time.perf_counter()

    effective_doc_ids = (
        [d for d in req.doc_ids if d in session_doc_ids]
        if req.doc_ids else session_doc_ids
    )
    if not effective_doc_ids:
        raise ValueError("No usable documents in session.")

    # ── Retrieve per-document then merge ───────────────────────────────────────
    all_lc_docs: List[LCDocument] = []
    k_per_doc = max(req.top_k // max(len(effective_doc_ids), 1), 3)
    top_n_per_doc = max(req.rerank_top_n // max(len(effective_doc_ids), 1), 2)

    for doc_id in effective_doc_ids:
        resp = search(SearchRequest(
            query=req.instruction,
            mode=req.search_mode,
            top_k=k_per_doc,
            rerank=True,
            rerank_top_n=top_n_per_doc,
            filters=SearchFilters(doc_id=doc_id),
        ))
        for hit in resp.results:
            meta = {
                "chunk_id":      hit.chunk_id,
                "doc_id":        hit.doc_id,
                "filename":      hit.filename,
                "doc_type":      hit.doc_type,
                "page_start":    hit.page_start,
                "page_end":      hit.page_end,
                "relevance_score": hit.final_score,
            }
            all_lc_docs.append(LCDocument(page_content=hit.text, metadata=meta))

    # Global re-sort and trim
    all_lc_docs.sort(key=lambda d: float(d.metadata.get("relevance_score", 0)), reverse=True)
    top_docs = all_lc_docs[: req.rerank_top_n]

    if not top_docs:
        raise ValueError("No relevant chunks retrieved — try a broader query.")

    # ── Build LCEL chain ───────────────────────────────────────────────────────
    llm = ChatOpenAI(model=OPENAI_CHAT_MODEL, temperature=0.1, max_tokens=2048)
    chain = _PROMPT | llm | StrOutputParser()

    draft_text = chain.invoke({
        "system_instruction": _DRAFT_PROMPTS.get(req.draft_type, _DRAFT_PROMPTS["custom"]),
        "grounding_rule":     _GROUNDING_RULE,
        "evidence_block":     _format_evidence(top_docs),
        "instruction":        req.instruction,
    })

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    filenames_used = {d.metadata.get("filename", "") for d in top_docs}

    # ── Build evidence list for response ───────────────────────────────────────
    evidence = [
        EvidenceChunk(
            chunk_id=d.metadata.get("chunk_id", ""),
            doc_id=d.metadata.get("doc_id", ""),
            filename=d.metadata.get("filename", ""),
            page_start=int(d.metadata.get("page_start", 0)),
            page_end=int(d.metadata.get("page_end", 0)),
            text=d.page_content,
            final_score=float(d.metadata.get("relevance_score", 0.0)),
        )
        for d in top_docs
    ]

    logger.info(
        "Draft generated: session=%s | docs=%d | chunks=%d | %.0fms",
        session_id, len(effective_doc_ids), len(top_docs), elapsed_ms,
    )

    return DraftResponse(
        session_id=session_id,
        instruction=req.instruction,
        draft_type=req.draft_type,
        draft_text=draft_text,
        evidence=evidence,
        documents_used=sorted(filenames_used),
        total_chunks_used=len(top_docs),
        search_mode=req.search_mode,
        generation_ms=elapsed_ms,
        model=OPENAI_CHAT_MODEL,
        grounding_note=(
            f"Grounded in {len(top_docs)} chunks from {len(filenames_used)} document(s). "
            "Claims absent from source are marked [NOT IN SOURCE DOCUMENTS]."
        ),
    )