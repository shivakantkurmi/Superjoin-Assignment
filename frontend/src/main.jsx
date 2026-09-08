import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
  return response.json();
}

function App() {
  const [documents, setDocuments] = useState([]);
  const [facts, setFacts] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [processingErrors, setProcessingErrors] = useState([]);
  const [selectedFact, setSelectedFact] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function refresh() {
    const [nextDocuments, nextFacts, nextRelationships, nextErrors] = await Promise.all([
      request("/documents"), request("/facts"), request("/relationships"), request("/processing-errors")
    ]);
    setDocuments(nextDocuments);
    setFacts(nextFacts);
    setRelationships(nextRelationships);
    setProcessingErrors(nextErrors);
  }

  useEffect(() => { refresh().catch((error) => setMessage(error.message)); }, []);

  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMessage(`Processing ${file.name}...`);
    try {
      const form = new FormData();
      form.append("file", file);
      await request("/documents/upload", { method: "POST", body: form });
      await refresh();
      setMessage("Document uploaded and page text extracted.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); event.target.value = ""; }
  }

  const counts = {
    corroborations: relationships.filter((item) => item.relationship_type === "CORROBORATES").length,
    contradictions: relationships.filter((item) => item.relationship_type === "CONTRADICTS").length,
    reconciles: relationships.filter((item) => item.relationship_type === "RECONCILES").length
  };

  return <main>
    <header className="topbar"><div><p className="kicker">FACT KNOWLEDGE LAYER</p><h1>Evidence, organized.</h1></div><label className={`upload ${busy ? "disabled" : ""}`}><input type="file" accept="application/pdf,.pdf" onChange={upload} disabled={busy} />{busy ? "PROCESSING" : "+ UPLOAD PDF"}</label></header>
    {message && <p className="notice">{message}</p>}
    <section className="metrics">
      <Metric label="Documents" value={documents.length} />
      <Metric label="Facts" value={facts.length} />
      <Metric label="Corroborations" value={counts.corroborations} tone="green" />
      <Metric label="Contradictions" value={counts.contradictions} tone="red" />
      <Metric label="Reconciled" value={counts.reconciles} tone="amber" />
    </section>
    <section className="workspace">
      <div className="panel"><div className="panel-heading"><h2>Extracted facts</h2><span>{facts.length} records</span></div>
        {facts.length === 0 ? <Empty text="Upload a PDF to begin building the layer." /> : <div className="fact-list">{facts.map((fact) => <button className="fact" key={fact.id} onClick={() => setSelectedFact(fact)}><div><strong>{fact.subject}</strong><span>{fact.predicate}</span></div><div className="fact-value">{String(fact.value || fact.object || "-")}<small>{fact.time?.label || "No period"}</small></div><Status value={fact.status} /></button>)}</div>}
      </div>
      <div className="panel"><div className="panel-heading"><h2>Relationships</h2><span>{relationships.length} links</span></div>
        {relationships.length === 0 ? <Empty text="Related facts will appear here after comparison." /> : <div className="relationship-list">{relationships.map((item, index) => <article className="relationship" key={item.id || index}><Status value={item.relationship_type} /><p>{item.explanation}</p><small>Confidence {Math.round((item.confidence || 0) * 100)}%</small></article>)}</div>}
      </div>
    </section>
    {processingErrors.length > 0 && <section className="panel processing-notes"><div className="panel-heading"><h2>Processing notes</h2><span>{processingErrors.length} reported</span></div><div className="relationship-list">{processingErrors.map((item, index) => <article className="relationship" key={`${item.document_id}-${index}`}><Status value="EVIDENCE_FAILED" /><p>{item.message}</p><small>Document {item.document_id}</small></article>)}</div></section>}
    {selectedFact && <aside className="evidence"><button className="close" onClick={() => setSelectedFact(null)}>CLOSE</button><p className="kicker">SOURCE EVIDENCE</p><h2>{selectedFact.subject}</h2><p className="predicate">{selectedFact.predicate}</p><div className="quote">"{selectedFact.evidence?.quote || "Evidence is unavailable."}"</div><dl><dt>Document</dt><dd>{selectedFact.evidence?.document_id || "-"}</dd><dt>Page</dt><dd>{selectedFact.evidence?.page_number || "-"}</dd><dt>Verification</dt><dd>{selectedFact.status}</dd></dl></aside>}
  </main>;
}

function Metric({ label, value, tone = "" }) { return <div className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong></div>; }
function Status({ value }) { return <span className={`status ${String(value).toLowerCase()}`}>{value}</span>; }
function Empty({ text }) { return <div className="empty">{text}</div>; }

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);