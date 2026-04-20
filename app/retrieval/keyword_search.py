import json
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever


class SessionBM25Store:
    """
    Builds and persists a BM25 corpus per session.
    Persistence here stores the source docs so BM25 can be rebuilt on load.
    """

    def __init__(self, persist_directory: str = "./bm25_store"):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

    def _session_file(self, session_id: str) -> Path:
        return self.persist_directory / f"{session_id}.json"

    def _serialize_docs(self, docs: List[Document]) -> List[dict]:
        return [
            {
                "page_content": d.page_content,
                "metadata": d.metadata,
            }
            for d in docs
        ]

    def _deserialize_docs(self, rows: List[dict]) -> List[Document]:
        return [
            Document(
                page_content=row["page_content"],
                metadata=row.get("metadata", {}),
            )
            for row in rows
        ]

    def add_documents(self, session_id: str, docs: List[Document]) -> None:
        existing = self.load_documents(session_id)
        all_docs = existing + docs
        self._session_file(session_id).write_text(
            json.dumps(self._serialize_docs(all_docs), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_documents(self, session_id: str) -> List[Document]:
        fp = self._session_file(session_id)
        if not fp.exists():
            return []

        rows = json.loads(fp.read_text(encoding="utf-8"))
        return self._deserialize_docs(rows)

    def retriever(self, session_id: str, k: int = 10) -> BM25Retriever:
        docs = self.load_documents(session_id)
        retriever = BM25Retriever.from_documents(
            docs,
            bm25_params={"k1": 1.5, "b": 0.75},
        )
        retriever.k = k
        return retriever