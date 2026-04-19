from typing import List

from langchain_core.documents import Document

from app.models.schemas import ProcessedDocument
from app.processors.chunker import chunks_to_lc_documents
from app.retrieval.vector_store import SessionVectorStore
from app.retrieval.keyword_search import SessionBM25Store


class SessionIngestService:
    def __init__(
        self,
        vector_store: SessionVectorStore,
        bm25_store: SessionBM25Store,
    ):
        self.vector_store = vector_store
        self.bm25_store = bm25_store

    def ingest_processed_documents(
        self,
        session_id: str,
        processed_docs: List[ProcessedDocument],
    ) -> List[Document]:
        lc_docs: List[Document] = []

        for processed_doc in processed_docs:
            docs = chunks_to_lc_documents(processed_doc)
            for d in docs:
                d.metadata["session_id"] = session_id
            lc_docs.extend(docs)

        if lc_docs:
            self.vector_store.add_documents(session_id, lc_docs)
            self.bm25_store.add_documents(session_id, lc_docs)

        return lc_docs