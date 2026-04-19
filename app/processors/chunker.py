import uuid
from typing import List

from langchain_core.documents import Document

from ...config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS
from app.models.schemas import DocumentChunk, PageResult, ProcessedDocument


def chunk_pages(pages: List[PageResult], doc_id: str) -> List[DocumentChunk]:
    """
    Produce overlapping text chunks across all pages while preserving
    page provenance.
    """
    chunks: List[DocumentChunk] = []

    page_boundaries: List[tuple[int, int, int]] = []  # (char_start, char_end, page_number)
    full_text_parts: List[str] = []
    cursor = 0

    for page in pages:
        text = page.cleaned_text
        if not text.strip():
            continue

        start = cursor
        full_text_parts.append(text)
        cursor += len(text) + 1
        page_boundaries.append((start, cursor - 1, page.page_number))

    full_text = "\n".join(full_text_parts)
    total_len = len(full_text)

    if total_len == 0:
        return chunks

    def char_to_page(char_idx: int) -> int:
        for start, end, pg in page_boundaries:
            if start <= char_idx <= end:
                return pg
        return page_boundaries[-1][2] if page_boundaries else 1

    pos = 0
    chunk_index = 0

    while pos < total_len:
        end = min(pos + CHUNK_SIZE_CHARS, total_len)

        if end < total_len:
            for boundary_char in [". ", ".\n", "\n\n", "\n"]:
                boundary_pos = full_text.rfind(boundary_char, pos, end)
                if boundary_pos != -1 and boundary_pos > pos + (CHUNK_SIZE_CHARS // 2):
                    end = boundary_pos + len(boundary_char)
                    break

        chunk_text = full_text[pos:end].strip()

        if chunk_text:
            page_start = char_to_page(pos)
            page_end = char_to_page(end - 1)

            chunks.append(
                DocumentChunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=chunk_text,
                    page_start=page_start,
                    page_end=page_end,
                    char_start=pos,
                    char_end=end,
                    chunk_index=chunk_index,
                    metadata={
                        "word_count": len(chunk_text.split()),
                        "char_count": len(chunk_text),
                    },
                )
            )
            chunk_index += 1

        pos = max(pos + 1, end - CHUNK_OVERLAP_CHARS)

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