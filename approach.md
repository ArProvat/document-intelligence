# Approach

## 1. System Design

This system is a session-scoped document intelligence and grounded drafting pipeline for legal-style work. It has five main layers:

1. API layer
   - FastAPI endpoints in `main.py`
   - Session creation, file upload, draft generation, and draft feedback
2. Document processing layer
   - PDF, image, and `.xlsx` ingestion
   - Native extraction where possible, OCR where needed, multimodal fallback for hard pages
3. Retrieval layer
   - Dense vector retrieval with Chroma
   - Sparse keyword retrieval with BM25
   - Weighted ensemble plus reranking
4. Draft generation layer
   - Query rewrite for retrieval
   - Evidence assembly
   - Grounded first-draft generation
5. Draft improvement layer
   - Capture operator edits
   - Extract reusable style rules
   - Reinject those rules into future generation

High-level request flow:

```text
Client
  -> POST /sessions
  -> POST /sessions/{session_id}/files
      -> processor pipeline
      -> chunking
      -> vector + keyword ingestion
  -> POST /sessions/{session_id}/drafts
      -> retrieval query rewrite
      -> hybrid retrieval + rerank
      -> evidence-grounded draft generation
      -> draft run stored
  -> POST /drafts/{draft_id}/feedback
      -> async feedback job
      -> structured diff
      -> rule extraction
      -> rule reinforce / decay / merge
```

## 2. How The Processor Works

### Supported inputs

- PDF
- Image files: `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.webp`
- Excel: `.xlsx`

### Main processing path

`process_document()` routes by file type and produces one `ProcessedDocument` with:

- document metadata
- page-level extraction results
- extracted entities
- document chunks
- warnings
- quality score

### PDF processing

PDF processing is hybrid:

- If a page has a usable text layer, the system extracts text natively with PyMuPDF.
- If a page looks scanned or too short, it renders the page as an image and runs OCR.
- Native-text pages also attempt table extraction with `pdfplumber`.

This gives better accuracy than using OCR on every page and preserves structure when the PDF already contains real text.

### Image processing

Images go through an OCR preparation pipeline before Tesseract:

- scale up if too small
- grayscale
- denoise
- contrast enhancement
- deskew
- sharpen

After OCR, the text is cleaned and scored.

### Multimodal fallback for low-quality pages

If OCR is weak, empty, or too short, the system falls back to an OpenAI vision-capable model. This is especially useful for:

- handwritten notes
- faint scans
- low-quality photos of documents
- pages where OCR misses text blocks or table content

The fallback is page-level. It only replaces OCR output when the fallback result is better, so the system does not blindly trust the vision model.

### XLSX processing

Each worksheet is treated as a page-like unit:

- rows are read with `openpyxl`
- sheet content is flattened into readable text
- the same rows are also stored as structured table data

This preserves spreadsheet content for both normal chunking and table-aware chunking.

### Document-level outputs

After page extraction, the processor computes:

- `avg_confidence`
- `low_confidence_pages`
- `doc_type`
- extracted entities
- chunk list
- processing warnings
- `quality_score`

## 3. How Table Handling Works

Tables are handled as first-class content, not just plain text.

### Native and spreadsheet tables

- PDF tables are extracted with `pdfplumber` when possible.
- `.xlsx` sheets are naturally available as table rows.

### Table chunking strategy

The chunker creates dedicated table chunks in addition to normal text chunks.

For each table:

- the first row is treated as the header when available
- body rows are grouped into blocks
- if the table is large, it is split by row groups
- the header is repeated in each table chunk

Each table chunk carries metadata such as:

- `chunk_kind = table`
- `chunk_method = table_block`
- `table_index`
- `table_row_start`
- `table_row_end`
- `table_row_count`
- `table_column_count`

This improves retrieval because the model can fetch a specific table block instead of a flattened page dump.

### Current behavior on scanned tables

Scanned tables inside poor-quality PDFs or images are harder because they may not have true row and column structure. The current system handles them through OCR and multimodal fallback text extraction. That means:

- the text can still be retrieved
- row and cell structure is weaker than native PDF tables or `.xlsx`

## 4. How Chunking Works

Chunking is context-aware and built with LangChain's `RecursiveCharacterTextSplitter`.

### Text chunking

The splitter prefers larger semantic boundaries first:

- section-like breaks
- article / clause markers
- sheet boundaries
- paragraphs
- lines
- sentences
- spaces

This is better than fixed-width chunking because it reduces the chance of splitting a legal clause or important paragraph in the middle.

### Chunk metadata

Every chunk keeps traceability metadata such as:

- `doc_id`
- `chunk_id`
- `page_start`
- `page_end`
- `char_start`
- `char_end`
- `chunk_index`

For text chunks, the system also records:

- `chunk_method = langchain_recursive`
- `chunk_kind = text`
- `page_span`

This metadata is later used for evidence grounding.

## 5. How Retrieval Works

The retrieval layer is hybrid, session-scoped, and evidence-oriented.

### Dense retrieval

Dense retrieval uses:

- Chroma as the vector store
- OpenAI embeddings: `text-embedding-3-large`

Documents are stored with `session_id` metadata so retrieval is isolated to the active session.

### Sparse retrieval

Sparse retrieval uses:

- BM25 from LangChain community retrievers
- per-session persisted JSON corpus

BM25 is useful for exact phrases, names, section numbers, and queries where literal token overlap matters.

### Ensemble retrieval

The system combines both retrievers using LangChain's `EnsembleRetriever`:

- dense weight: `0.6`
- sparse weight: `0.4`

This balances semantic recall and exact-match precision.

### Reranking

The ensemble output is passed through `FlashrankRerank` inside a `ContextualCompressionRetriever`.

That means:

- more chunks can be recalled upstream
- only the strongest chunks survive reranking
- the final draft model sees a tighter, more relevant evidence set

## 6. How Evidence-Grounded Draft Generation Works

Draft generation follows a two-step LLM pattern.

### Step 1: Rewrite the operator request into a retrieval query

The system first converts the operator's request into a retrieval-oriented query. This prompt is specialized by draft type, for example:

- title review summary
- case fact summary
- notice-related summary
- document checklist
- internal memo

The goal is to retrieve the right chunks before drafting starts.

### Step 2: Retrieve evidence and generate the draft

After retrieval and reranking, the system formats the selected chunks into explicit evidence blocks:

```text
[Evidence 1]
filename: ...
doc_id: ...
chunk_id: ...
pages: ...
doc_type: ...
text: ...
```

The draft model is then instructed to:

- use only the provided evidence
- avoid invented facts
- call out missing or conflicting information
- produce a useful first-pass draft

### Why this is grounded

The draft is grounded because:

- retrieval is session-scoped
- chunk metadata preserves page references
- the prompt contains explicit evidence blocks
- the model is told to stay inside that evidence set

The API also returns the evidence list with the draft so the client can inspect what supported the output.

## 7. How The Improvement Loop Works

The improvement loop is designed to learn operator preferences without fine-tuning.

### Stage 1: Capture the edit

When a draft is generated, the system stores a `draft_id` and the draft run context:

- `user_id`
- `session_id`
- `draft_type`
- instructions
- retrieval query
- original draft
- evidence used
- applied style rules

When the operator edits the draft, they submit:

- edited draft
- optional operator notes

The system creates a feedback job record and processes it asynchronously.

### Stage 2: Build a structured diff

The feedback service compares the original and edited drafts using block-level diffing. It stores structured entries like:

- operation type
- removed text
- added text

This is more useful than storing two raw text blobs because it exposes what changed in a machine-readable way.

### Stage 3: Extract reusable rules

The structured diff, original draft, edited draft, draft type, retrieval query, and operator notes are sent to an LLM with a rule-extraction prompt.

The model is asked to infer reusable guidance such as:

- structure preferences
- tone preferences
- completeness expectations
- citation preferences
- formatting habits
- analytical expectations

Each extracted rule is stored with:

- description
- category
- before example
- after example
- applicable draft types
- confidence
- support count
- status

### Stage 4: Merge, reinforce, decay

The system does not just append every new rule forever.

It also:

- merges near-duplicate rules using normalized keys and fuzzy similarity
- reinforces rules that keep appearing in edits
- decays rules that were applied but do not appear to matter
- prunes weak stale rules
- supports manual disable, enable, and delete operations

This keeps the rule set usable over time instead of turning into noise.

### Stage 5: Inject rules into future drafting

Before generating a new draft, the system fetches active rules for the same user and draft type, filtered by confidence.

These are appended to the prompt under `OPERATOR STYLE PREFERENCES`.

This creates a learning loop:

- operator edits draft
- system extracts generalizable rules
- future drafts start closer to operator preference

## 8. Async Behavior And Server Safety

The API avoids blocking the event loop for heavy work:

- document processing runs in a threadpool
- ingestion runs in a threadpool
- draft generation runs in a threadpool
- feedback learning runs as an async background job

This matters because OCR, PDF parsing, embedding generation, and rule extraction are expensive operations.

The feedback API therefore behaves like a job system:

- submit feedback
- receive `feedback_id` with `pending` status
- poll feedback status until `completed` or `failed`

## 9. Storage Model

The current storage model is mixed:

### In-memory

- session registry
- session-to-document mapping
- processed document store

These reset if the server restarts.

### Persisted on disk

- Chroma vector store
- BM25 source corpus
- draft improvement store

The improvement store persists:

- draft runs
- feedback events
- style rules

This means learned writing preferences survive restarts, while active upload sessions currently do not.

## 10. Why This Design Fits Legal Document Work

This design is a practical fit for legal-style drafting because it combines:

- native extraction for clean source documents
- OCR for scanned material
- multimodal fallback for handwriting and low-quality pages
- table-aware chunking for structured records
- hybrid retrieval for both semantics and exact language
- evidence-grounded prompting to reduce hallucination
- a feedback loop that learns how a specific operator wants drafts written

In short, the system is not just a basic RAG pipeline. It is a session-based drafting workflow that turns operator edits into reusable drafting policy over time.
