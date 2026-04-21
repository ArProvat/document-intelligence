import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.models.api_schemas import (
    CreateSessionRequest,
    SessionResponse,
    SessionUploadResponse,
    DraftRequest,
    DraftResponse,
    DraftFeedbackRequest,
    DraftFeedbackResponse,
    RuleDeleteResponse,
    StyleRule,
    DraftType,
)
from app.models.schemas import UploadResponse
from app.processors.document_processor import process_document
from app.retrieval.vector_store import SessionVectorStore
from app.retrieval.keyword_search import SessionBM25Store
from app.retrieval.hybrid_search import HybridSessionRetriever
from app.services.session_store import InMemorySessionStore
from app.services.document_store import InMemoryDocumentStore
from app.services.session_ingest_service import SessionIngestService
from app.services.draft_generation import DraftGenerationService
from app.services.draft_improvement import DraftImprovementService, DraftImprovementStore

app = FastAPI(title="Legal Grounded Drafting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_store = InMemorySessionStore()
document_store = InMemoryDocumentStore()

vector_store = SessionVectorStore()
bm25_store = SessionBM25Store()
ingest_service = SessionIngestService(vector_store, bm25_store)

hybrid_retriever = HybridSessionRetriever(
    vector_store=vector_store,
    bm25_store=bm25_store,
    vector_weight=0.6,
    keyword_weight=0.4,
    k=10,
    fetch_k=20,
    top_n=8,
)

draft_improvement_store = DraftImprovementStore()
draft_improvement_service = DraftImprovementService(draft_improvement_store)
draft_service = DraftGenerationService(hybrid_retriever, draft_improvement_service)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest):
    session = session_store.create_session(req.user_id)
    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at,
        document_ids=session.document_ids,
    )


@app.post("/sessions/{session_id}/files", response_model=SessionUploadResponse)
async def upload_files(session_id: str, files: List[UploadFile] = File(...)):
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    processed_docs = []
    upload_results = []

    for upload in files:
        suffix = Path(upload.filename).suffix.lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(upload.file, tmp)
            temp_path = Path(tmp.name)

        try:
            processed = await run_in_threadpool(process_document, temp_path, upload.filename)
            processed_docs.append(processed)
            document_store.save(processed)
            session_store.add_document(session_id, processed.doc_id)

            upload_results.append(
                UploadResponse(
                    doc_id=processed.doc_id,
                    filename=processed.filename,
                    status="processed",
                    message="File processed successfully",
                    processing_time_seconds=0.0,
                    quality_score=processed.quality_score,
                    doc_type=processed.doc_type.value,
                    total_pages=processed.total_pages,
                    avg_confidence=processed.avg_confidence,
                    chunk_count=len(processed.chunks),
                    entity_count=len(processed.entities),
                    warnings=[w.message for w in processed.warnings],
                )
            )
        finally:
            temp_path.unlink(missing_ok=True)

    await run_in_threadpool(ingest_service.ingest_processed_documents, session_id, processed_docs)

    return SessionUploadResponse(
        session_id=session_id,
        uploaded_count=len(upload_results),
        documents=upload_results,
    )


@app.post("/sessions/{session_id}/drafts", response_model=DraftResponse)
async def generate_draft(session_id: str, req: DraftRequest):
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.document_ids:
        raise HTTPException(
            status_code=400,
            detail="No documents uploaded for this session",
        )

    return await draft_service.agenerate_draft(
        session.user_id,
        session_id,
        req.draft_type,
        req.instructions,
    )


@app.post("/drafts/{draft_id}/feedback", response_model=DraftFeedbackResponse)
async def submit_draft_feedback(
    draft_id: str,
    req: DraftFeedbackRequest,
    background_tasks: BackgroundTasks,
):
    try:
        feedback_response = draft_improvement_service.submit_feedback_job(
            draft_id=draft_id,
            edited_draft=req.edited_draft,
            operator_notes=req.operator_notes,
        )
        background_tasks.add_task(
            draft_improvement_service.process_feedback_job,
            feedback_response.feedback_id,
        )
        return feedback_response
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/feedback/{feedback_id}", response_model=DraftFeedbackResponse)
async def get_feedback_status(feedback_id: str):
    try:
        return draft_improvement_service.get_feedback_status(feedback_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/users/{user_id}/style-rules", response_model=List[StyleRule])
async def list_style_rules(user_id: str, draft_type: DraftType | None = None):
    return draft_improvement_service.list_rules_for_user(
        user_id=user_id,
        draft_type=draft_type,
        include_disabled=True,
    )


@app.post("/users/{user_id}/style-rules/{rule_id}/disable", response_model=StyleRule)
async def disable_style_rule(user_id: str, rule_id: str):
    try:
        return draft_improvement_service.disable_rule(user_id, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/users/{user_id}/style-rules/{rule_id}/enable", response_model=StyleRule)
async def enable_style_rule(user_id: str, rule_id: str):
    try:
        return draft_improvement_service.enable_rule(user_id, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/users/{user_id}/style-rules/{rule_id}", response_model=RuleDeleteResponse)
async def delete_style_rule(user_id: str, rule_id: str):
    try:
        draft_improvement_service.delete_rule_for_user(user_id, rule_id)
        return RuleDeleteResponse(rule_id=rule_id, deleted=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
