from typing import List, Optional

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document


class SessionVectorStore:
    """
    Session-scoped Chroma vector store using OpenAI embeddings.
    """

    def __init__(self, persist_directory: str = "./chroma_langchain_db"):
        self.persist_directory = persist_directory
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large",
            dimensions=1024,
        )

    def _get_store(self, session_id: str) -> Chroma:
        return Chroma(
            collection_name=f"legal_session_{session_id}",
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
            collection_metadata={
                "hnsw:space": "cosine",
                "hnsw:construction_ef": 100,
                "hnsw:M": 16,
            },
        )

    def add_documents(self, session_id: str, documents: List[Document]) -> None:
        if not documents:
            return
        self._get_store(session_id).add_documents(documents)

    def retriever(self, session_id: str, k: int = 10, fetch_k: int = 20):
        return self._get_store(session_id).as_retriever(
            search_kwargs={
                "k": k,
                "fetch_k": fetch_k,
                "filter": {"session_id": session_id},
            }
        )

    def similarity_search(
        self,
        session_id: str,
        query: str,
        k: int = 10,
    ) -> List[Document]:
        return self._get_store(session_id).similarity_search(
            query,
            k=k,
            filter={"session_id": session_id},
        )

    def delete_session(self, session_id: str) -> None:
        self._get_store(session_id).delete(where={"session_id": session_id})