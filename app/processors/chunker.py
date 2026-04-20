import uuid
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS
from app.models.schemas import DocumentChunk, PageResult, ProcessedDocument

CONTEXT_AWARE_SEPARATORS = [
    "\n\nSECTION ",
    "\n\nSection ",
    "\n\nARTICLE ",
    "\n\nArticle ",
    "\n\nCLAUSE ",
    "\n\nClause ",
    "\n\nSHEET: ",
    "\n\nSheet: ",
    "\n\n",
    "\n",
    ". ",
    "; ",
    ", ",
    " ",
    "",
]


def _build_full_text(pages: List[PageResult]) -> tuple[str, List[tuple[int, int, int]]]:
    page_boundaries: List[tuple[int, int, int]] = []
    full_text_parts: List[str] = []
    cursor = 0

    for page in pages:
        text = page.cleaned_text.strip()
        if not text:
            continue

        separator = "\n\n" if full_text_parts else ""
        cursor += len(separator)
        start = cursor
        full_text_parts.append(f"{separator}{text}")
        cursor += len(text)
        page_boundaries.append((start, cursor - 1, page.page_number))

    return "".join(full_text_parts), page_boundaries


def _char_to_page(char_idx: int, page_boundaries: List[tuple[int, int, int]]) -> int:
    for start, end, page_number in page_boundaries:
        if start <= char_idx <= end:
            return page_number

    if not page_boundaries:
        return 1

    if char_idx < page_boundaries[0][0]:
        return page_boundaries[0][2]

    return page_boundaries[-1][2]


def chunk_pages(pages: List[PageResult], doc_id: str) -> List[DocumentChunk]:
    """
    Use LangChain's recursive splitter to preserve paragraphs and section-like
    boundaries before falling back to smaller separators.
    """
    full_text, page_boundaries = _build_full_text(pages)
    if not full_text:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_CHARS,
        chunk_overlap=CHUNK_OVERLAP_CHARS,
        separators=CONTEXT_AWARE_SEPARATORS,
        add_start_index=True,
        keep_separator=True,
    )
    split_docs = splitter.create_documents([full_text], metadatas=[{"doc_id": doc_id}])

    chunks: List[DocumentChunk] = []

    for chunk_index, split_doc in enumerate(split_docs):
        chunk_text = split_doc.page_content.strip()
        if not chunk_text:
            continue

        start_index = int(split_doc.metadata.get("start_index", 0))
        end_index = start_index + len(split_doc.page_content)
        page_start = _char_to_page(start_index, page_boundaries)
        page_end = _char_to_page(max(start_index, end_index - 1), page_boundaries)

        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=chunk_text,
                page_start=page_start,
                page_end=page_end,
                char_start=start_index,
                char_end=end_index,
                chunk_index=chunk_index,
                metadata={
                    "word_count": len(chunk_text.split()),
                    "char_count": len(chunk_text),
                    "chunk_method": "langchain_recursive",
                    "page_span": page_end - page_start + 1,
                },
            )
        )

    return chunks


def chunks_to_lc_documents(processed_doc: ProcessedDocument) -> List[Document]:
    """
    Convert ProcessedDocument.chunks into LangChain Document objects
    with flat metadata for vector + keyword retrieval.
    """
    lc_docs: List[Document] = []

    for chunk in processed_doc.chunks:
        metadata = {
            "doc_id": processed_doc.doc_id,
            "filename": processed_doc.filename,
            "file_type": processed_doc.file_type,
            "doc_type": processed_doc.doc_type.value,
            "doc_type_confidence": processed_doc.doc_type_confidence,
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "quality_score": processed_doc.quality_score,
            "avg_confidence": processed_doc.avg_confidence,
            "extraction_method": processed_doc.extraction_method.value,
            "is_usable": processed_doc.is_usable,
        }

        for k, v in chunk.metadata.items():
            metadata[f"chunk_{k}"] = v

        lc_docs.append(
            Document(
                page_content=chunk.text,
                metadata=metadata,
            )
        )

    return lc_docs
