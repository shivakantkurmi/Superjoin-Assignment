import { StrictMode, useEffect, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// ── Skeleton rows shown while data is loading ─────────────────────────────
function SkeletonFacts() {
  return (
    <div className="skeleton-list">
      {[1, 2, 3, 4, 5].map((n) => (
        <div className="skeleton-row" key={n} style={{ opacity: 1 - n * 0.12 }}>
          <div>
            <div className="skel title" />
            <div className="skel sub" />
          </div>
          <div>
            <div className="skel value" />
            <div className="skel sub" style={{ width: "55%" }} />
          </div>
          <div className="skel badge" />
        </div>
      ))}
    </div>
  );
}

function SkeletonRelationships() {
  return (
    <div className="skeleton-list">
      {[1, 2, 3].map((n) => (
        <div className="relationship" key={n} style={{ opacity: 1 - n * 0.2 }}>
          <div className="skel badge" style={{ width: 96 }} />
          <div className="skel" style={{ width: "90%", marginTop: 12 }} />
          <div className="skel" style={{ width: "65%", marginTop: 6 }} />
          <div className="skel sub" style={{ width: 80, marginTop: 10 }} />
        </div>
      ))}
    </div>
  );
}

// ── Small reusable components ─────────────────────────────────────────────
function Metric({ label, value, tone = "" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusBadge({ value }) {
  return <span className={`status ${String(value || "").toLowerCase()}`}>{value}</span>;
}

function EvidenceLine({ fact }) {
  const evidence = fact?.evidence;
  if (!evidence) return null;
  return (
    <small className="source-evidence">
      Source: {evidence.document_name || evidence.document_id || "document"}, page {evidence.page_number || "—"}
      {evidence.quote ? ` — "${evidence.quote}"` : ""}
    </small>
  );
}

function Empty({ icon = "○", text }) {
  return (
    <div className="empty">
      <span className="empty-icon">{icon}</span>
      {text}
    </div>
  );
}

// ── Main app ──────────────────────────────────────────────────────────────
function App() {
  const [documents, setDocuments]       = useState([]);
  const [facts, setFacts]               = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [errors, setErrors]             = useState([]);
  const [selectedFact, setSelectedFact] = useState(null);

  // Loading states: "init" = first load, "refresh" = background refresh, null = idle
  const [loading, setLoading]    = useState("init");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress]   = useState(0);
  const [notice, setNotice]       = useState(null);   // { text, error? }
  const [uploadStage, setUploadStage] = useState(""); // human-readable stage label

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading((prev) => prev === "init" ? "init" : "refresh");
    try {
      const [docs, fts, rels, errs] = await Promise.all([
        request("/documents"),
        request("/facts"),
        request("/relationships"),
        request("/processing-errors"),
      ]);
      setDocuments(docs);
      setFacts(fts);
      setRelationships(rels);
      setErrors(errs);
    } catch (e) {
      setNotice({ text: e.message, error: true });
    } finally {
      setLoading(null);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";

    setUploading(true);
    setProgress(5);
    setUploadStage("Uploading…");
    setNotice(null);

    try {
      const form = new FormData();
      form.append("file", file);

      setProgress(15);
      setUploadStage("Extracting pages with PyMuPDF…");
      await new Promise((r) => setTimeout(r, 400));

      setProgress(35);
      setUploadStage("Running local fact extraction…");

      const doc = await request("/documents/upload", { method: "POST", body: form });

      setProgress(80);
      setUploadStage("Building embeddings and comparing facts…");
      await new Promise((r) => setTimeout(r, 300));

      setProgress(95);
      setUploadStage("Saving to database…");
      await refresh(true);

      setProgress(100);
      const status = doc.status || "COMPLETED";
      setNotice({
        text: `✓ ${file.name} processed — ${doc.facts_count ?? "–"} facts · ${doc.relationships_count ?? "–"} relationships · status: ${status}`,
      });
    } catch (e) {
      setNotice({ text: e.message, error: true });
    } finally {
      setTimeout(() => setProgress(0), 600);
      setUploading(false);
      setUploadStage("");
    }
  }

  const counts = {
    corroborations: relationships.filter((r) => r.relationship_type === "CORROBORATES").length,
    contradictions: relationships.filter((r) => r.relationship_type === "CONTRADICTS").length,
    reconciled:     relationships.filter((r) => r.relationship_type === "RECONCILES").length,
  };
  const visibleErrors = errors.filter((item) =>
    !/\b(?:llm|gemini|groq|provider|reason(?:ing|er))\b/i.test(
      `${item.stage || ""} ${item.message || ""}`
    )
  );

  const isFirstLoad = loading === "init";

  return (
    <main>
      {/* ── Topbar ─────────────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <p className="kicker">Fact Knowledge Layer</p>
          <h1>Evidence, organised.</h1>
        </div>
        <label className={`upload ${uploading ? "disabled" : ""}`} id="upload-label">
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={upload}
            disabled={uploading}
            aria-label="Upload PDF"
          />
          {uploading ? <><span className="spinner" /> PROCESSING</> : "+ UPLOAD PDF"}
        </label>
      </header>

      {/* ── Progress bar ────────────────────────────────────────────────── */}
      {uploading && (
        <div className="progress-track" role="progressbar" aria-valuenow={progress}>
          <div className="progress-bar" style={{ width: `${progress}%` }} />
        </div>
      )}

      {/* ── Upload status banner ────────────────────────────────────────── */}
      {uploading && uploadStage && (
        <div className="status-banner">
          <span className="spinner" />
          <span className="status-banner-text">{uploadStage}</span>
        </div>
      )}

      {/* ── Notice ──────────────────────────────────────────────────────── */}
      {notice && (
        <p className={`notice ${notice.error ? "error" : ""}`} role="status">
          {notice.text}
        </p>
      )}

      {/* ── Metrics ─────────────────────────────────────────────────────── */}
      <section className="metrics" aria-label="Summary metrics">
        <Metric label="Documents"     value={isFirstLoad ? "—" : documents.length} />
        <Metric label="Facts"         value={isFirstLoad ? "—" : facts.length} />
        <Metric label="Corroborated"  value={isFirstLoad ? "—" : counts.corroborations} tone="green" />
        <Metric label="Contradicted"  value={isFirstLoad ? "—" : counts.contradictions} tone="red" />
        <Metric label="Reconciled"    value={isFirstLoad ? "—" : counts.reconciled}     tone="amber" />
      </section>

      {/* ── Workspace ───────────────────────────────────────────────────── */}
      <section className="workspace">
        {/* Facts panel */}
        <div className="panel" role="region" aria-label="Extracted facts">
          <div className="panel-heading">
            <h2>Extracted facts</h2>
            <span>{isFirstLoad ? "…" : `${facts.length} records`}</span>
          </div>
          {isFirstLoad ? (
            <SkeletonFacts />
          ) : facts.length === 0 ? (
            <Empty icon="📄" text="Upload a PDF to start building the knowledge layer." />
          ) : (
            <div className="fact-list">
              {facts.map((fact) => (
                <button
                  className="fact"
                  key={fact.id}
                  onClick={() => setSelectedFact(fact)}
                  aria-pressed={selectedFact?.id === fact.id}
                >
                  <div>
                    <strong>{fact.subject}</strong>
                    <span>{fact.predicate}</span>
                    <EvidenceLine fact={fact} />
                  </div>
                  <div className="fact-value">
                    {String(fact.value ?? fact.object ?? "—")}
                    <small>{fact.time?.label || "No period"}</small>
                  </div>
                  <StatusBadge value={fact.status} />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Relationships panel */}
        <div className="panel" role="region" aria-label="Fact relationships">
          <div className="panel-heading">
            <h2>Relationships</h2>
            <span>{isFirstLoad ? "…" : `${relationships.length} links`}</span>
          </div>
          {isFirstLoad ? (
            <SkeletonRelationships />
          ) : relationships.length === 0 ? (
            <Empty icon="⟷" text="Relationships between facts appear here after processing." />
          ) : (
            <div className="relationship-list">
              {relationships.map((item, i) => (
                <article className="relationship" key={item.id || i}>
                  <StatusBadge value={item.relationship_type} />
                  {item.fact_a && item.fact_b && (
                    <div className="relationship-sources">
                      <small>
                        {item.fact_a.subject} · {item.fact_a.predicate} ({item.fact_a.evidence?.document_name || "source"})
                        {item.fact_a.evidence?.quote ? ` — "${item.fact_a.evidence.quote}"` : ""}
                      </small>
                      {"  ↔  "}
                      <small>
                        {item.fact_b.subject} · {item.fact_b.predicate} ({item.fact_b.evidence?.document_name || "source"})
                        {item.fact_b.evidence?.quote ? ` — "${item.fact_b.evidence.quote}"` : ""}
                      </small>
                    </div>
                  )}
                  <p>{item.explanation}</p>
                  <small>Confidence {Math.round((item.confidence || 0) * 100)}%</small>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── Processing errors ────────────────────────────────────────────── */}
      {visibleErrors.length > 0 && (
        <section className="panel processing-notes" aria-label="Processing notes">
          <div className="panel-heading">
            <h2>Processing notes</h2>
            <span>{visibleErrors.length} reported</span>
          </div>
          <div className="relationship-list">
            {visibleErrors.map((item, i) => (
              <article className="relationship" key={`${item.document_id}-${i}`}>
                <StatusBadge value="EVIDENCE_FAILED" />
                <p>{item.message}</p>
                <small>Document {item.document_id}</small>
              </article>
            ))}
          </div>
        </section>
      )}

      {/* ── Evidence side panel ──────────────────────────────────────────── */}
      {selectedFact && (
        <aside className="evidence" role="dialog" aria-modal="true" aria-label="Source evidence">
          <div className="evidence-header">
            <p className="kicker" style={{ margin: 0 }}>Source Evidence</p>
            <button className="close" onClick={() => setSelectedFact(null)} aria-label="Close evidence panel">
              CLOSE ✕
            </button>
          </div>
          <div className="evidence-body">
            <h2>{selectedFact.subject}</h2>
            <p className="predicate">{selectedFact.predicate}</p>
            <div className="quote">
              "{selectedFact.evidence?.quote || "Evidence text unavailable."}"
            </div>
            <dl>
              <dt>Document</dt>
              <dd>{selectedFact.evidence?.document_id || "—"}</dd>
              <dt>Page</dt>
              <dd>{selectedFact.evidence?.page_number || "—"}</dd>
              <dt>Value</dt>
              <dd>{String(selectedFact.value ?? selectedFact.object ?? "—")}</dd>
              {selectedFact.time?.label && <><dt>Period</dt><dd>{selectedFact.time.label}</dd></>}
              {selectedFact.unit && <><dt>Unit</dt><dd>{selectedFact.unit}</dd></>}
              <dt>Confidence</dt>
              <dd>{Math.round((selectedFact.confidence || 0) * 100)}%</dd>
              <dt>Status</dt>
              <dd><StatusBadge value={selectedFact.status} /></dd>
            </dl>
          </div>
        </aside>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);