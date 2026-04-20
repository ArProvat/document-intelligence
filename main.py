import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.api_schemas import (
    CreateSessionRequest,
    SessionResponse,
    SessionUploadResponse,
    DraftRequest,
    DraftResponse,
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

draft_service = DraftGenerationService(hybrid_retriever)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sessions", response_model=SessionResponse)
def create_session(req: CreateSessionRequest):
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
            processed = process_document(temp_path, upload.filename)
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

    ingest_service.ingest_processed_documents(session_id, processed_docs)

    return SessionUploadResponse(
        session_id=session_id,
        uploaded_count=len(upload_results),
        documents=upload_results,
    )


@app.post("/sessions/{session_id}/drafts", response_model=DraftResponse)
def generate_draft(session_id: str, req: DraftRequest):
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.document_ids:
        raise HTTPException(
            status_code=400,
            detail="No documents uploaded for this session",
        )

    return draft_service.generate_draft(
        session_id=session_id,
        draft_type=req.draft_type,
        instructions=req.instructions,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
