from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from langchain_community.document_compressors import FlashrankRerank

from app.retrieval.vector_store import SessionVectorStore
from app.retrieval.keyword_search import SessionBM25Store


class HybridSessionRetriever:
    """
    Hybrid retriever:
    - Chroma dense retriever
    - BM25 sparse retriever
    - weighted ensemble
    - Flashrank reranking/compression
    """

    def __init__(
        self,
        vector_store: SessionVectorStore,
        bm25_store: SessionBM25Store,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        k: int = 10,
        fetch_k: int = 20,
        top_n: int = 8,
    ):
        self.vector_store = vector_store
        self.bm25_store = bm25_store
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.k = k
        self.fetch_k = fetch_k
        self.top_n = top_n

    def base_retriever(self, session_id: str):
        dense = self.vector_store.retriever(
            session_id=session_id,
            k=self.k,
            fetch_k=self.fetch_k,
        )
        sparse = self.bm25_store.retriever(
            session_id=session_id,
            k=self.k,
        )

        return EnsembleRetriever(
            retrievers=[dense, sparse],
            weights=[self.vector_weight, self.keyword_weight],
        )

    def rerank_retriever(self, session_id: str):
        compressor = FlashrankRerank(top_n=self.top_n)
        return ContextualCompressionRetriever(
            base_retriever=self.base_retriever(session_id),
            base_compressor=compressor,
        )
