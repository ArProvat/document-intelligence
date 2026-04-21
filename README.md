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
```

## Choose The Right Doc

- [README.md](</C:/Project/document_intelligence/README.md:1>) for setup and day-1 usage
- [ARCHITECTURE.md](</C:/Project/document_intelligence/ARCHITECTURE.md:1>) for system design and internal flow
- [API_EXAMPLES.md](</C:/Project/document_intelligence/API_EXAMPLES.md:1>) for request and response examples

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

This is the recommended way to run the API because OCR and PDF tooling need native system packages.

```powershell
docker compose up --build
```

Then open:

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

Notes:

- Chroma, BM25, uploads, and processed artifacts are mounted into Docker volumes.
- Session state is in memory, so active sessions reset when the container restarts.
- Learned style rules are stored in `./draft_learning_store`.
- In the current `docker-compose.yml`, `draft_learning_store` is not mounted as a named volume, so learned rules may be lost if the container is recreated or rebuilt.

## Local Backend Setup

Use local setup only if you want to run outside Docker.

### 1. Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Install native OCR and PDF dependencies

You also need native tools that Python packages do not install for you:

- `Tesseract OCR`
- `Poppler`

On Windows, make sure both are installed and available on `PATH`.

### 4. Start the API

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

## End-to-End Workflow

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

### 6. Poll feedback status

Feedback processing is asynchronous. Submit feedback, then poll the feedback endpoint until it finishes.

### 7. Generate again

Future drafts for the same user and draft type will include the learned style rules in the prompt.

## Improvement Rules

Improvement rules are stored `user-wise`, not `session-wise`.

That means:

- draft runs and feedback events keep session context
- reusable style rules are promoted to the user level
- future drafts use rules filtered by `user_id` and `draft_type`

## Persistence Model

- session registry
- session-to-document mapping
- processed document store

- Chroma data
- BM25 source corpus
- draft learning store

If the server restarts:

- uploaded session references reset
- Chroma and BM25 stay available if their volumes remain mounted
- learned style rules remain available only if `draft_learning_store` is also persisted

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

## Current Limitations

- Session state is not persisted across restarts
- Scanned tables do not yet have strong structural row and column reconstruction
- The system depends on external model APIs for embeddings, drafting, and multimodal fallback
- OCR quality still depends on input quality

## Next Good Improvements

- persistent session store
- persist `draft_learning_store` in Docker
- stronger scanned-table reconstruction
- object storage for uploaded files
- background job queue for ingestion and draft generation
- auth and multi-tenant controls
