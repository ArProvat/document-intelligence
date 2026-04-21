import uuid
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS, TABLE_CHUNK_MAX_ROWS
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


def _page_start_offsets(page_boundaries: List[tuple[int, int, int]]) -> dict[int, int]:
    return {page_number: start for start, _end, page_number in page_boundaries}


def _normalize_table(table: List[List[str]]) -> List[List[str]]:
    normalized: List[List[str]] = []

    for row in table:
        cells = [str(cell).strip() for cell in row if str(cell).strip()]
        if cells:
            normalized.append(cells)

    return normalized


def _format_table_chunk(
    page_number: int,
    table_index: int,
    header_row: List[str],
    body_rows: List[List[str]],
    row_start: int,
) -> str:
    lines = [
        f"Table block on page {page_number}",
        f"Table {table_index + 1}",
    ]

    if header_row:
        lines.append("Columns: " + " | ".join(header_row))

    for offset, row in enumerate(body_rows, start=row_start):
        lines.append(f"Row {offset}: " + " | ".join(row))

    return "\n".join(lines)


def _table_chunks_for_page(
    page: PageResult,
    doc_id: str,
    starting_chunk_index: int,
    page_start_offsets: dict[int, int],
) -> List[DocumentChunk]:
    chunks: List[DocumentChunk] = []
    chunk_index = starting_chunk_index
    page_char_start = page_start_offsets.get(page.page_number, 0)

    for table_index, table in enumerate(page.tables):
        rows = _normalize_table(table)
        if not rows:
            continue

        header_row = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []

        if not data_rows:
            table_text = _format_table_chunk(
                page_number=page.page_number,
                table_index=table_index,
                header_row=header_row,
                body_rows=[header_row],
                row_start=1,
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=table_text,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    char_start=page_char_start,
                    char_end=page_char_start + len(table_text),
                    chunk_index=chunk_index,
                    metadata={
                        "word_count": len(table_text.split()),
                        "char_count": len(table_text),
                        "chunk_method": "table_block",
                        "chunk_kind": "table",
                        "table_index": table_index,
                        "table_row_start": 1,
                        "table_row_end": 1,
                        "table_row_count": 1,
                        "table_column_count": len(header_row),
                        "header_included": True,
                    },
                )
            )
            chunk_index += 1
            continue

        block_rows: List[List[str]] = []
        block_start = 1

        for row_number, row in enumerate(data_rows, start=2):
            candidate_rows = block_rows + [row]
            candidate_text = _format_table_chunk(
                page_number=page.page_number,
                table_index=table_index,
                header_row=header_row,
                body_rows=candidate_rows,
                row_start=block_start,
            )

            if (
                block_rows
                and (
                    len(candidate_rows) > TABLE_CHUNK_MAX_ROWS
                    or len(candidate_text) > CHUNK_SIZE_CHARS
                )
            ):
                table_text = _format_table_chunk(
                    page_number=page.page_number,
                    table_index=table_index,
                    header_row=header_row,
                    body_rows=block_rows,
                    row_start=block_start,
                )
                chunks.append(
                    DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        doc_id=doc_id,
                        text=table_text,
                        page_start=page.page_number,
                        page_end=page.page_number,
                        char_start=page_char_start,
                        char_end=page_char_start + len(table_text),
                        chunk_index=chunk_index,
                        metadata={
                            "word_count": len(table_text.split()),
                            "char_count": len(table_text),
                            "chunk_method": "table_block",
                            "chunk_kind": "table",
                            "table_index": table_index,
                            "table_row_start": block_start,
                            "table_row_end": block_start + len(block_rows) - 1,
                            "table_row_count": len(block_rows),
                            "table_column_count": len(header_row),
                            "header_included": True,
                        },
                    )
                )
                chunk_index += 1
                block_rows = [row]
                block_start = row_number
            else:
                block_rows = candidate_rows

        if block_rows:
            table_text = _format_table_chunk(
                page_number=page.page_number,
                table_index=table_index,
                header_row=header_row,
                body_rows=block_rows,
                row_start=block_start,
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=table_text,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    char_start=page_char_start,
                    char_end=page_char_start + len(table_text),
                    chunk_index=chunk_index,
                    metadata={
                        "word_count": len(table_text.split()),
                        "char_count": len(table_text),
                        "chunk_method": "table_block",
                        "chunk_kind": "table",
                        "table_index": table_index,
                        "table_row_start": block_start,
                        "table_row_end": block_start + len(block_rows) - 1,
                        "table_row_count": len(block_rows),
                        "table_column_count": len(header_row),
                        "header_included": True,
                    },
                )
            )
            chunk_index += 1

    return chunks


def chunk_pages(pages: List[PageResult], doc_id: str) -> List[DocumentChunk]:
    """
    Use LangChain's recursive splitter to preserve paragraphs and section-like
    boundaries before falling back to smaller separators.
    """
    full_text, page_boundaries = _build_full_text(pages)
    page_start_offsets = _page_start_offsets(page_boundaries)
    chunks: List[DocumentChunk] = []

    if full_text:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE_CHARS,
            chunk_overlap=CHUNK_OVERLAP_CHARS,
            separators=CONTEXT_AWARE_SEPARATORS,
            add_start_index=True,
            keep_separator=True,
        )
        split_docs = splitter.create_documents([full_text], metadatas=[{"doc_id": doc_id}])

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
                        "chunk_kind": "text",
                        "page_span": page_end - page_start + 1,
                    },
                )
            )

    next_chunk_index = len(chunks)

    for page in pages:
        if not page.has_tables or not page.tables:
            continue

        table_chunks = _table_chunks_for_page(
            page=page,
            doc_id=doc_id,
            starting_chunk_index=next_chunk_index,
            page_start_offsets=page_start_offsets,
        )
        chunks.extend(table_chunks)
        next_chunk_index += len(table_chunks)

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
