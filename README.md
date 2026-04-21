# Document Intelligence API

Session-based document processing, retrieval, grounded drafting, and operator feedback learning for legal-style workflows.

This project takes uploaded PDFs, images, and `.xlsx` files, extracts text and tables, indexes the content for retrieval, generates evidence-grounded drafts, and learns reusable operator style rules from edit feedback.

## What It Does

- Processes `PDF`, image, and `.xlsx` files
- Uses native extraction when available, OCR when needed
- Falls back to OpenAI vision for low-confidence pages, handwritten notes, and poor scans
- Chunks narrative text and tables separately
- Indexes content into:
  - Chroma for dense retrieval
  - BM25 for keyword retrieval
- Generates grounded drafts from retrieved evidence
- Learns user-level writing preferences from edited drafts
- Applies learned style rules to future drafts

## Repository Layout

```text
app/
  models/         Pydantic request/response and domain schemas
  processors/     PDF, image, xlsx, OCR, fallback extraction, chunking
  retrieval/      Chroma, BM25, hybrid retrieval, reranking
  services/       ingestion, draft generation, improvement loop
frontend/         React test app
main.py           FastAPI app and API routes
config.py         runtime settings
README.md         setup and usage
ARCHITECTURE.md   system design notes
API_EXAMPLES.md   sample requests and responses
approach.md       deeper implementation walkthrough
```

## Main API Flow

1. Create a session
2. Upload one or more files into that session
3. Generate a draft for a chosen draft type
4. Submit an edited draft as feedback
5. Poll feedback status
6. Generate future drafts with learned rules applied

## Supported Draft Types

- `title_review_summary`
- `case_fact_summary`
- `notice_related_summary`
- `document_checklist`
- `internal_memo`

## Requirements

- Python `3.12`
- Node.js `18+` for the React frontend
- OpenAI API key
- Docker and Docker Compose if using the containerized setup

## Environment

Create a `.env` file in the repo root:

```env
OPENAI_API_KEY=your_openai_api_key
```

Optional runtime knobs are defined in `config.py`, including:

- OCR threshold
- multimodal fallback enablement
- fallback model
- chunk size and overlap
- table chunk row limit

## Quick Start With Docker

This is the simplest way to run the API.

```powershell
docker compose up --build
```

Then open:

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

Notes:

- Chroma, BM25, uploads, and processed artifacts are mounted into Docker volumes.
- Session state is in memory, so active sessions reset when the container restarts.
- Learned style rules persist on disk inside the container workspace.

## Local Backend Setup

### 1. Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Start the API

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Local Frontend Setup

The frontend is a small React test app for exercising the API.

```powershell
Set-Location frontend
npm install
npm run dev
```

Then open:

- `http://localhost:5173`

The frontend expects the backend on `http://localhost:8000`.

## API Endpoints

### Core workflow

- `GET /health`
- `POST /sessions`
- `POST /sessions/{session_id}/files`
- `POST /sessions/{session_id}/drafts`

### Improvement loop

- `POST /drafts/{draft_id}/feedback`
- `GET /feedback/{feedback_id}`
- `GET /users/{user_id}/style-rules`
- `POST /users/{user_id}/style-rules/{rule_id}/disable`
- `POST /users/{user_id}/style-rules/{rule_id}/enable`
- `DELETE /users/{user_id}/style-rules/{rule_id}`

See [API_EXAMPLES.md](</C:/Project/document_intelligence/API_EXAMPLES.md:1>) for sample payloads and responses.

## Typical End-to-End Workflow

### 1. Create a session

Use a stable `user_id` if you want style rules to accumulate across sessions.

### 2. Upload files

Upload PDFs, images, or `.xlsx` files to that session.

### 3. Generate a first draft

Choose a draft type and optional instructions.

### 4. Edit the draft

A human operator refines the output.

### 5. Submit feedback

Send the edited draft and optional notes. The system extracts reusable style rules in the background.

### 6. Generate again

Future drafts for the same user and draft type will include the learned style rules in the prompt.

## Processing Behavior

### PDFs

- Native text extraction with PyMuPDF where possible
- OCR for scanned pages
- table extraction with `pdfplumber`

### Images

- Tesseract OCR after preprocessing
- OpenAI vision fallback for low-confidence or too-short OCR results

### XLSX

- worksheets treated as page-like units
- rows stored as text and table data

## Retrieval Strategy

- Dense retrieval: OpenAI embeddings + Chroma
- Sparse retrieval: BM25
- Fusion: weighted ensemble
- Final selection: Flashrank reranking

## Grounded Drafting

Drafts are generated from retrieved evidence blocks. The model is instructed to:

- use only retrieved evidence
- avoid inventing facts
- call out missing or conflicting information

This is not meant to replace legal review. It is a first-pass drafting and summarization system.

## Improvement Rules

Improvement rules are stored `user-wise`, not `session-wise`.

That means:

- draft runs and feedback events keep session context
- reusable style rules are promoted to the user level
- future drafts use rules filtered by `user_id` and `draft_type`

## Persistence Model

### In memory

- session registry
- session-to-document mapping
- processed document store

### On disk

- Chroma data
- BM25 source corpus
- draft learning store

If the server restarts:

- uploaded session references reset
- learned style rules remain available

## Validation And Useful Commands

Backend syntax check:

```powershell
python -m compileall app main.py
```

Frontend build:

```powershell
Set-Location frontend
npm run build
```

## Recommended Reading Order

1. [README.md](</C:/Project/document_intelligence/README.md:1>)
2. [ARCHITECTURE.md](</C:/Project/document_intelligence/ARCHITECTURE.md:1>)
3. [API_EXAMPLES.md](</C:/Project/document_intelligence/API_EXAMPLES.md:1>)
4. [approach.md](</C:/Project/document_intelligence/approach.md:1>)

## Current Limitations

- Session state is not persisted across restarts
- Scanned tables do not yet have strong structural row and column reconstruction
- The system depends on external model APIs for embeddings, drafting, and multimodal fallback
- OCR quality still depends on input quality

## Next Good Improvements

- persistent session store
- stronger scanned-table reconstruction
- object storage for uploaded files
- background job queue for ingestion and draft generation
- auth and multi-tenant controls
