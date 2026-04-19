from typing import Dict, Optional, List

from app.models.schemas import ProcessedDocument


class InMemoryDocumentStore:
    def __init__(self):
        self._docs: Dict[str, ProcessedDocument] = {}

    def save(self, doc: ProcessedDocument) -> None:
        self._docs[doc.doc_id] = doc

    def get(self, doc_id: str) -> Optional[ProcessedDocument]:
        return self._docs.get(doc_id)

    def get_many(self, doc_ids: List[str]) -> List[ProcessedDocument]:
        return [self._docs[d] for d in doc_ids if d in self._docs]