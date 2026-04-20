import { useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

const DRAFT_TYPES = [
  { value: "title_review_summary", label: "Title Review Summary" },
  { value: "case_fact_summary", label: "Case Fact Summary" },
  { value: "notice_related_summary", label: "Notice Related Summary" },
  { value: "document_checklist", label: "Document Checklist" },
  { value: "internal_memo", label: "Internal Memo" },
];

function buildUrl(path) {
  return `${API_BASE}${path}`;
}

async function parseJsonResponse(response) {
  const text = await response.text();

  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function getErrorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

function JsonPanel({ title, data }) {
  if (!data) {
    return null;
  }

  return (
    <section className="panel output-panel">
      <div className="panel-header">
        <h3>{title}</h3>
      </div>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}

function App() {
  const [userId, setUserId] = useState("demo-user");
  const [sessionId, setSessionId] = useState("");
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [draftType, setDraftType] = useState(DRAFT_TYPES[0].value);
  const [instructions, setInstructions] = useState("");

  const [health, setHealth] = useState(null);
  const [sessionResponse, setSessionResponse] = useState(null);
  const [uploadResponse, setUploadResponse] = useState(null);
  const [draftResponse, setDraftResponse] = useState(null);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");

  const hasSession = Boolean(sessionId.trim());
  const selectedFileNames = selectedFiles.map((file) => file.name);

  async function runAction(actionName, callback) {
    setBusyAction(actionName);
    setError("");

    try {
      await callback();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusyAction("");
    }
  }

  async function checkHealth() {
    await runAction("health", async () => {
      const response = await fetch(buildUrl("/health"));
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "Health check failed");
      }

      setHealth(data);
    });
  }

  async function createSession() {
    await runAction("session", async () => {
      const response = await fetch(buildUrl("/sessions"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ user_id: userId }),
      });
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "Failed to create session");
      }

      setSessionResponse(data);
      setSessionId(data.session_id);
      setUploadResponse(null);
      setDraftResponse(null);
    });
  }

  async function uploadFiles() {
    if (!hasSession) {
      setError("Create or paste a session ID before uploading.");
      return;
    }

    if (selectedFiles.length === 0) {
      setError("Choose at least one file before uploading.");
      return;
    }

    await runAction("upload", async () => {
      const formData = new FormData();

      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });

      const response = await fetch(buildUrl(`/sessions/${sessionId}/files`), {
        method: "POST",
        body: formData,
      });
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "File upload failed");
      }

      setUploadResponse(data);
      setDraftResponse(null);
    });
  }

  async function generateDraft() {
    if (!hasSession) {
      setError("Create or paste a session ID before generating a draft.");
      return;
    }

    await runAction("draft", async () => {
      const response = await fetch(buildUrl(`/sessions/${sessionId}/drafts`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          draft_type: draftType,
          instructions: instructions.trim() || null,
        }),
      });
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "Draft generation failed");
      }

      setDraftResponse(data);
    });
  }

  return (
    <div className="shell">
      <div className="hero">
        <div>
          <p className="eyebrow">React Test Console</p>
          <h1>Document Intelligence API Runner</h1>
          <p className="lede">
            Create a session, upload PDFs, Excel sheets, or images, then generate a grounded draft
            without switching back to Swagger.
          </p>
        </div>
        <div className="hero-meta">
          <span className="meta-chip">API base: {API_BASE}</span>
          <span className="meta-chip">Allowed files: pdf, xlsx, png, jpg, jpeg, tiff, tif, bmp, webp</span>
        </div>
      </div>

      <div className="notice">
        Sessions live in backend memory. If the API container restarts, create a new
        session before uploading or drafting again.
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="grid">
        <section className="panel">
          <div className="panel-header">
            <h2>1. Connectivity</h2>
            <button
              type="button"
              onClick={checkHealth}
              disabled={Boolean(busyAction)}
            >
              {busyAction === "health" ? "Checking..." : "Check Health"}
            </button>
          </div>

          <p className="panel-copy">
            Confirms the frontend can reach the FastAPI server through the local Vite
            proxy or the configured API base URL.
          </p>

          <JsonPanel title="Health Response" data={health} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>2. Session</h2>
            <button
              type="button"
              onClick={createSession}
              disabled={Boolean(busyAction) || !userId.trim()}
            >
              {busyAction === "session" ? "Creating..." : "Create Session"}
            </button>
          </div>

          <label className="field">
            <span>User ID</span>
            <input
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              placeholder="demo-user"
            />
          </label>

          <label className="field">
            <span>Active Session ID</span>
            <input
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value)}
              placeholder="Generated session_id will appear here"
            />
          </label>

          <JsonPanel title="Session Response" data={sessionResponse} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>3. Upload Files</h2>
            <button
              type="button"
              onClick={uploadFiles}
              disabled={Boolean(busyAction) || !hasSession || selectedFiles.length === 0}
            >
              {busyAction === "upload" ? "Uploading..." : "Upload to Session"}
            </button>
          </div>

          <label className="field">
            <span>Choose Documents</span>
            <input
              type="file"
              multiple
              accept=".pdf,.xlsx,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp"
              onChange={(event) => setSelectedFiles(Array.from(event.target.files || []))}
            />
          </label>

          <div className="file-list">
            {selectedFileNames.length ? (
              selectedFileNames.map((fileName) => (
                <span key={fileName} className="file-chip">
                  {fileName}
                </span>
              ))
            ) : (
              <span className="muted">No files selected yet.</span>
            )}
          </div>

          <JsonPanel title="Upload Response" data={uploadResponse} />
        </section>

        <section className="panel full-width">
          <div className="panel-header">
            <h2>4. Generate Draft</h2>
            <button
              type="button"
              onClick={generateDraft}
              disabled={Boolean(busyAction) || !hasSession}
            >
              {busyAction === "draft" ? "Generating..." : "Generate Draft"}
            </button>
          </div>

          <div className="draft-grid">
            <label className="field">
              <span>Draft Type</span>
              <select
                value={draftType}
                onChange={(event) => setDraftType(event.target.value)}
              >
                {DRAFT_TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field field-wide">
              <span>Instructions</span>
              <textarea
                rows="6"
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder="Optional operator instructions, for example: emphasize timeline gaps and missing title documents."
              />
            </label>
          </div>

          {draftResponse ? (
            <div className="draft-output">
              <section className="result-card">
                <h3>Retrieval Query</h3>
                <p>{draftResponse.retrieval_query}</p>
              </section>

              <section className="result-card">
                <h3>Draft</h3>
                <div className="draft-text">{draftResponse.draft}</div>
              </section>

              <section className="result-card">
                <h3>Evidence</h3>
                <div className="evidence-list">
                  {draftResponse.evidence?.map((item) => (
                    <article key={`${item.doc_id}-${item.chunk_id}`} className="evidence-card">
                      <strong>{item.filename}</strong>
                      <span>
                        pages {item.page_start}-{item.page_end}
                      </span>
                      <code>{item.chunk_id}</code>
                      <p>{item.snippet}</p>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          ) : (
            <p className="panel-copy">
              Draft results will appear here after you upload at least one document
              into the active session.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

export default App;
