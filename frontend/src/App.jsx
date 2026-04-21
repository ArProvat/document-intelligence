import { useEffect, useState } from "react";

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

function RuleBadge({ rule, onDisable, onEnable, onDelete, busy }) {
  const isDisabled = rule.status === "disabled";

  return (
    <article className="rule-card">
      <div className="rule-header">
        <strong>{rule.category}</strong>
        <span>
          {rule.status} | confidence {(rule.confidence ?? 0).toFixed(2)}
        </span>
      </div>
      <p>{rule.description}</p>
      {"support_count" in rule ? <span>support {rule.support_count}</span> : null}
      {onDisable || onEnable || onDelete ? (
        <div className="rule-actions">
          {isDisabled ? (
            <button type="button" className="secondary-button" onClick={() => onEnable?.(rule)} disabled={busy}>
              Enable
            </button>
          ) : (
            <button type="button" className="secondary-button" onClick={() => onDisable?.(rule)} disabled={busy}>
              Disable
            </button>
          )}
          <button type="button" className="danger-button" onClick={() => onDelete?.(rule)} disabled={busy}>
            Delete
          </button>
        </div>
      ) : null}
    </article>
  );
}

function DiffCard({ entry, index }) {
  return (
    <article className="diff-card">
      <strong>
        {index + 1}. {entry.operation}
      </strong>
      <div className="diff-grid">
        <div>
          <span className="diff-label">Before</span>
          <pre>{entry.before || "(empty)"}</pre>
        </div>
        <div>
          <span className="diff-label">After</span>
          <pre>{entry.after || "(empty)"}</pre>
        </div>
      </div>
    </article>
  );
}

function App() {
  const [userId, setUserId] = useState("demo-user");
  const [sessionId, setSessionId] = useState("");
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [draftType, setDraftType] = useState(DRAFT_TYPES[0].value);
  const [instructions, setInstructions] = useState("");
  const [editedDraft, setEditedDraft] = useState("");
  const [operatorNotes, setOperatorNotes] = useState("");

  const [health, setHealth] = useState(null);
  const [sessionResponse, setSessionResponse] = useState(null);
  const [uploadResponse, setUploadResponse] = useState(null);
  const [draftResponse, setDraftResponse] = useState(null);
  const [feedbackResponse, setFeedbackResponse] = useState(null);
  const [styleRules, setStyleRules] = useState([]);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");

  const hasSession = Boolean(sessionId.trim());
  const hasDraft = Boolean(draftResponse?.draft_id);
  const selectedFileNames = selectedFiles.map((file) => file.name);
  const pollingFeedback = feedbackResponse?.status === "pending" || feedbackResponse?.status === "processing";

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

  async function loadStyleRules(nextDraftType = draftType) {
    if (!userId.trim()) {
      setError("Enter a user ID before loading style rules.");
      return;
    }

    await runAction("rules", async () => {
      const params = new URLSearchParams();
      if (nextDraftType) {
        params.set("draft_type", nextDraftType);
      }

      const response = await fetch(
        buildUrl(`/users/${encodeURIComponent(userId)}/style-rules?${params.toString()}`),
      );
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "Failed to load style rules");
      }

      setStyleRules(data);
    });
  }

  async function refreshFeedbackStatus(feedbackId) {
    const response = await fetch(buildUrl(`/feedback/${feedbackId}`));
    const data = await parseJsonResponse(response);

    if (!response.ok) {
      throw new Error(data.detail || "Failed to load feedback status");
    }

    setFeedbackResponse(data);
    if (data.status === "completed") {
      setStyleRules(data.active_rules || []);
    }
  }

  useEffect(() => {
    if (!pollingFeedback || !feedbackResponse?.feedback_id) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      refreshFeedbackStatus(feedbackResponse.feedback_id).catch((err) => {
        setError(getErrorMessage(err));
      });
    }, 2000);

    return () => window.clearTimeout(timeoutId);
  }, [pollingFeedback, feedbackResponse?.feedback_id]);

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
      setFeedbackResponse(null);
      setEditedDraft("");
      setOperatorNotes("");
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
      setFeedbackResponse(null);
      setEditedDraft("");
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
      setFeedbackResponse(null);
      setEditedDraft(data.draft || "");
      await loadStyleRules(draftType);
    });
  }

  async function submitFeedback() {
    if (!hasDraft) {
      setError("Generate a draft before submitting operator feedback.");
      return;
    }

    if (!editedDraft.trim()) {
      setError("Edit or paste the revised draft before submitting feedback.");
      return;
    }

    await runAction("feedback", async () => {
      const response = await fetch(buildUrl(`/drafts/${draftResponse.draft_id}/feedback`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          edited_draft: editedDraft,
          operator_notes: operatorNotes.trim() || null,
        }),
      });
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || "Feedback submission failed");
      }

      setFeedbackResponse(data);
    });
  }

  async function changeRuleStatus(rule, action) {
    await runAction(`rule-${action}`, async () => {
      const method = action === "delete" ? "DELETE" : "POST";
      const suffix = action === "delete" ? "" : `/${action}`;
      const response = await fetch(
        buildUrl(`/users/${encodeURIComponent(userId)}/style-rules/${rule.rule_id}${suffix}`),
        { method },
      );
      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error(data.detail || `Failed to ${action} rule`);
      }

      await loadStyleRules();
      if (feedbackResponse?.status === "completed") {
        await refreshFeedbackStatus(feedbackResponse.feedback_id);
      }
    });
  }

  return (
    <div className="shell">
      <div className="hero">
        <div>
          <p className="eyebrow">React Test Console</p>
          <h1>Document Intelligence API Runner</h1>
          <p className="lede">
            Create a session, upload documents, generate a draft, then teach the system
            from your edits so later drafts inherit the same operator preferences.
          </p>
        </div>
        <div className="hero-meta">
          <span className="meta-chip">API base: {API_BASE}</span>
          <span className="meta-chip">Allowed files: pdf, xlsx, png, jpg, jpeg, tiff, tif, bmp, webp</span>
        </div>
      </div>

      <div className="notice">
        Sessions live in backend memory. Style rules persist separately and are scoped by user ID,
        so reuse the same user ID if you want the improvement loop to compound.
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="grid">
        <section className="panel">
          <div className="panel-header">
            <h2>1. Connectivity</h2>
            <button type="button" onClick={checkHealth} disabled={Boolean(busyAction)}>
              {busyAction === "health" ? "Checking..." : "Check Health"}
            </button>
          </div>
          <p className="panel-copy">
            Confirms the frontend can reach the FastAPI server through the local Vite proxy
            or the configured API base URL.
          </p>
          <JsonPanel title="Health Response" data={health} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>2. Session</h2>
            <button type="button" onClick={createSession} disabled={Boolean(busyAction) || !userId.trim()}>
              {busyAction === "session" ? "Creating..." : "Create Session"}
            </button>
          </div>

          <label className="field">
            <span>User ID</span>
            <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="demo-user" />
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
            <button type="button" onClick={generateDraft} disabled={Boolean(busyAction) || !hasSession}>
              {busyAction === "draft" ? "Generating..." : "Generate Draft"}
            </button>
          </div>

          <div className="draft-grid">
            <label className="field">
              <span>Draft Type</span>
              <select value={draftType} onChange={(event) => setDraftType(event.target.value)}>
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
                <h3>Draft Metadata</h3>
                <div className="meta-list">
                  <span>
                    <strong>Draft ID:</strong> {draftResponse.draft_id}
                  </span>
                  <span>
                    <strong>Draft Type:</strong> {draftResponse.draft_type}
                  </span>
                  <span>
                    <strong>Generated At:</strong> {draftResponse.generated_at}
                  </span>
                </div>
              </section>

              <section className="result-card">
                <h3>Retrieval Query</h3>
                <p>{draftResponse.retrieval_query}</p>
              </section>

              <section className="result-card">
                <h3>Applied Rules</h3>
                {draftResponse.applied_rules?.length ? (
                  <div className="rule-list">
                    {draftResponse.applied_rules.map((rule) => (
                      <RuleBadge key={rule.rule_id} rule={rule} />
                    ))}
                  </div>
                ) : (
                  <p className="panel-copy">No learned rules were applied to this draft yet.</p>
                )}
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
              Draft results will appear here after you upload at least one document into the active session.
            </p>
          )}
        </section>

        <section className="panel full-width">
          <div className="panel-header">
            <h2>5. Operator Feedback</h2>
            <button type="button" onClick={submitFeedback} disabled={Boolean(busyAction) || !hasDraft}>
              {busyAction === "feedback" ? "Submitting..." : "Submit Feedback"}
            </button>
          </div>

          <p className="panel-copy">
            Edit the generated draft the way a senior operator would. Feedback analysis now runs asynchronously,
            so the request returns immediately and the UI polls until the learning job finishes.
          </p>

          <label className="field">
            <span>Edited Draft</span>
            <textarea
              rows="14"
              value={editedDraft}
              onChange={(event) => setEditedDraft(event.target.value)}
              placeholder="Paste the operator-edited version here."
            />
          </label>

          <label className="field">
            <span>Operator Notes</span>
            <textarea
              rows="4"
              value={operatorNotes}
              onChange={(event) => setOperatorNotes(event.target.value)}
              placeholder="Optional note, e.g. always cite section numbers and open with a one-sentence executive summary."
            />
          </label>

          {feedbackResponse ? (
            <div className="draft-output">
              <section className="result-card">
                <h3>Feedback Job</h3>
                <div className="meta-list">
                  <span>
                    <strong>Feedback ID:</strong> {feedbackResponse.feedback_id}
                  </span>
                  <span>
                    <strong>Status:</strong> {feedbackResponse.status}
                  </span>
                  {feedbackResponse.error_message ? (
                    <span>
                      <strong>Error:</strong> {feedbackResponse.error_message}
                    </span>
                  ) : null}
                </div>
              </section>

              <section className="result-card">
                <h3>Extracted Rules</h3>
                {feedbackResponse.extracted_rules?.length ? (
                  <div className="rule-list">
                    {feedbackResponse.extracted_rules.map((rule) => (
                      <RuleBadge key={rule.rule_id} rule={rule} />
                    ))}
                  </div>
                ) : (
                  <p className="panel-copy">
                    {pollingFeedback
                      ? "Feedback is still processing."
                      : "No reusable rules were extracted from this edit."}
                  </p>
                )}
              </section>

              <section className="result-card">
                <h3>Structured Diff</h3>
                {feedbackResponse.structured_diff?.length ? (
                  <div className="diff-list">
                    {feedbackResponse.structured_diff.map((entry, index) => (
                      <DiffCard key={`${entry.operation}-${index}`} entry={entry} index={index} />
                    ))}
                  </div>
                ) : (
                  <p className="panel-copy">
                    {pollingFeedback ? "Waiting for structured diff extraction." : "No diff entries were recorded."}
                  </p>
                )}
              </section>
            </div>
          ) : (
            <p className="panel-copy">
              Feedback results will appear here after you submit an edited draft.
            </p>
          )}
        </section>

        <section className="panel full-width">
          <div className="panel-header">
            <h2>6. Learned Rules</h2>
            <button type="button" onClick={() => loadStyleRules()} disabled={Boolean(busyAction) || !userId.trim()}>
              {busyAction === "rules" ? "Loading..." : "Load Style Rules"}
            </button>
          </div>

          <p className="panel-copy">
            Rules are listed with their current status. Disabled rules stay stored but are excluded from future
            prompts until you re-enable them.
          </p>

          {styleRules.length ? (
            <div className="rule-list">
              {styleRules.map((rule) => (
                <RuleBadge
                  key={rule.rule_id}
                  rule={rule}
                  busy={Boolean(busyAction)}
                  onDisable={(selectedRule) => changeRuleStatus(selectedRule, "disable")}
                  onEnable={(selectedRule) => changeRuleStatus(selectedRule, "enable")}
                  onDelete={(selectedRule) => changeRuleStatus(selectedRule, "delete")}
                />
              ))}
            </div>
          ) : (
            <p className="panel-copy">
              No style rules loaded yet. Generate a draft, submit feedback, then load rules again.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

export default App;
