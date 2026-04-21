# Architecture Notes

## Overview

The system is a session-scoped RAG pipeline with a user-level learning loop.

Two design choices matter most:

1. Retrieval is `session-scoped`
   - each draft only sees the documents uploaded into the current session
2. style learning is `user-scoped`
   - reusable writing preferences survive across sessions for the same user

## Logical Components

### API layer

`main.py` exposes the workflow endpoints and coordinates:

- session creation
- file upload
- document ingestion
- draft generation
- feedback submission
- feedback polling
- style rule lifecycle operations

Expensive sync work is pushed through `run_in_threadpool`, and feedback learning is processed with `BackgroundTasks`.

### Processing layer

The processing layer converts raw files into `ProcessedDocument` objects.

Main responsibilities:

- detect file type
- extract text
- estimate confidence
- preserve page-level outputs
- extract tables when possible
- classify document type
- extract simple entities
- build chunks for retrieval

### Retrieval layer

The retrieval layer indexes chunks per session into:

- Chroma for dense vector retrieval
- BM25 for sparse keyword retrieval

It then builds:

- `EnsembleRetriever` for fusion
- `FlashrankRerank` for final selection

### Draft generation layer

The draft layer uses two prompts:

1. rewrite the operator request into a better retrieval query
2. generate a draft from retrieved evidence

The evidence is formatted with filename, chunk, page, and document metadata so the output can be traced back to source material.

### Improvement layer

The improvement layer stores draft runs, captures operator edits, extracts reusable style rules, and reinjects those rules into later prompts.

This is prompt adaptation, not model fine-tuning.

## End-to-End Data Flow

```text
upload file
  -> process into pages
  -> classify and chunk
  -> convert chunks into LangChain Documents
  -> write to Chroma and BM25

generate draft
  -> rewrite request into retrieval query
  -> hybrid retrieval
  -> rerank
  -> build evidence block
  -> fetch active style rules for user + draft type
  -> generate grounded draft
  -> save draft run

submit feedback
  -> save feedback job
  -> build structured diff
  -> extract general rules with LLM
  -> merge / reinforce / decay rules
  -> save updated rule set
```

## Processing Notes

### PDFs

PDF handling is hybrid:

- native text when real text exists
- OCR for scanned pages
- page-level table extraction with `pdfplumber`

This avoids wasting OCR on good PDFs while still supporting scans.

### Images

Images go through Tesseract after preprocessing:

- resize
- grayscale
- denoise
- contrast enhancement
- deskew
- sharpen

If the OCR result is weak, the system can ask an OpenAI vision model to transcribe the page.

### XLSX

Worksheets are treated as page-like units. Their rows are stored both as plain text and as table structures, which improves retrieval and drafting for structured business documents.

## Chunking Strategy

Chunking is split into two paths.

### Narrative chunks

Narrative text uses LangChain `RecursiveCharacterTextSplitter` with separators that favor:

- section boundaries
- article and clause markers
- sheet boundaries
- paragraphs
- smaller fallback separators

### Table chunks

Tables are chunked separately so they do not disappear into paragraph text.

Each table chunk:

- repeats the header
- groups rows into manageable blocks
- keeps table metadata for later retrieval

This is important for schedules, ledgers, registers, and spreadsheet-like evidence.

## Retrieval Notes

### Why hybrid retrieval

Legal-style drafting needs both:

- semantic recall
- exact lexical matching

Dense retrieval helps with paraphrased or conceptually similar content. BM25 helps with:

- names
- dates
- section numbers
- exact phrases
- unusual legal terms

The ensemble improves recall quality before reranking reduces noise.

### Why reranking matters

Without reranking, the final draft model may see too many partially relevant chunks. Reranking improves precision and makes the evidence block smaller and more focused.

## Grounding Model

The grounding model is prompt-based, not citation-verified generation.

Grounding comes from:

- session-filtered retrieval
- page-aware chunk metadata
- explicit evidence formatting
- instructions not to invent facts

The output is evidence-aware, but it is still a model-generated draft and should be reviewed by a human.

## Improvement Loop Design

The improvement loop follows five ideas:

### 1. Capture context, not just text

Each generated draft stores:

- user
- session
- draft type
- retrieval query
- draft text
- evidence
- applied rules

### 2. Use a structured diff

The edit is converted into before/after change blocks instead of being stored as two raw strings only.

### 3. Extract reusable rules

The LLM is prompted to infer general drafting preferences rather than case-specific corrections.

### 4. Merge and score rules over time

Rules are:

- merged when near-duplicate
- reinforced when repeated
- decayed when not validated
- pruned when weak

### 5. Inject rules into future prompts

Only active rules above the confidence threshold are added to the draft prompt.

## Storage Model

### Session-bound state

Currently stored in memory:

- sessions
- document references
- processed document cache

This makes development simple, but sessions reset on restart.

### Persistent state

Stored on disk:

- Chroma collections
- BM25 source corpus
- draft learning records

This means the learning loop survives restarts better than the session layer.

## Operational Notes

### Async behavior

The current system is not a full distributed job architecture, but it avoids blocking the FastAPI event loop for the heaviest operations.

### Failure surface

Main failure areas are:

- OCR quality
- external model/API availability
- large document latency
- session loss on restart

### Observability

The code logs useful document-processing metadata such as:

- document type
- confidence
- chunk count
- entity count
- quality score

## Design Tradeoffs

### What this design optimizes for

- ease of iteration
- understandable pipeline boundaries
- better-than-basic handling for messy real-world documents
- practical operator feedback learning

### What it does not yet optimize for

- full persistence of live sessions
- queue-backed large-scale async processing
- hard guarantees for citation correctness
- advanced scanned-table reconstruction

For a deeper implementation walkthrough, see [approach.md](</C:/Project/document_intelligence/approach.md:1>).
