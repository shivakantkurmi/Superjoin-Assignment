# Fact Knowledge Layer

A system that extracts meaningful facts from PDFs, links every fact to its source evidence, and identifies when facts corroborate, contradict, or can be reconciled across documents.

---

## Setup and Run Instructions

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Supabase project (PostgreSQL) — optional; the system falls back to in-memory storage without it
- A Google Gemini API key — optional; the pipeline runs locally without it; only ambiguous fact pairs use the LLM

### Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
Copy-Item .env.example .env
```

Edit `.env` and fill in your keys:

```env
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-3.7-flash
GEMINI_MODELS=gemini-3.7-flash,gemini-3.6-flash

GROQ_API_KEY=your-groq-key
GROQ_MODEL=openai/gpt-oss-20b

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_DB_URL=postgresql://postgres:password@db.your-project.supabase.co:5432/postgres

FRONTEND_ORIGINS=http://localhost:5173
```

If using Supabase, run the migration files in the SQL editor in order:

1. `supabase/migrations/0001_initial_schema.sql`
2. `supabase/migrations/0002_add_document_counts.sql`
3. `supabase/migrations/0003_fix_fact_column_types.sql`
4. `supabase/migrations/0004_add_chunk_id_to_evidence.sql`

Start the API (`.env` is automatically loaded via `python-dotenv`):

```powershell
uvicorn app.main:app --reload
```

API: `http://localhost:8000` · Docs: `http://localhost:8000/docs`

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, then upload a PDF using the **+ UPLOAD PDF** button.

### Tests

```powershell
python -m pytest tests/ -v
```

All 35 tests run without API keys or a database connection.

---

## Video Demo

Video demo link: [Watch the Loom demo](https://www.loom.com/share/fab93a09ef114d94a176797e051ea7e2)


---

## Approach

### Architecture

```mermaid
flowchart TD
    A[PDF Upload] --> B[PyMuPDF\npage-aware extraction]
    B --> C[Page-aware Chunking\nsentence-boundary aligned]
    C --> D[Text Normalization\nNFKC · hyphen · header dedup]
    D --> E[Local Candidate Extraction\nDeterministicFactExtractor\nregex + NLP · NO LLM]
    E --> F[Candidate Facts\nsubject · predicate · value\nunit · period · scope · quote]
    F --> G[Deterministic Normalization\nnumbers · scales · currencies\npercentages · periods · text]
    G --> H[MiniLM Embeddings\nall-MiniLM-L6-v2 · local]
    H --> I[FAISS Top-K Retrieval\nNOT the source of truth]
    I --> J[Candidate Fact Pairs]
    J --> K[Deterministic Comparison\nsubject · predicate · time\nscope · geo · value checks]
    K --> |CLEAR| L[Final Relationship]
    K --> |UNCLEAR| M[LLM Router\nambiguous pairs only]
    M --> N[Groq\nprimary]
    M --> O[Gemini\nfallback]
    N --> P[Validation\nPydantic schema +\nevidence grounding]
    O --> P
    L --> Q[Supabase PostgreSQL\nsource of truth]
    P --> Q
    Q --> R[FastAPI]
    R --> S[React UI]
```

Fact extraction happens locally using regex and NLP patterns — no LLM is involved in bulk PDF processing. Groq is tried first for the small number of fact pairs where deterministic comparison is genuinely uncertain, with Gemini as the fallback. If both LLM providers are unavailable, the relationship is marked `AMBIGUOUS` and processing continues.

### Key Decisions

- **Local-first extraction** — `DeterministicFactExtractor` identifies numerical values, percentages, currencies, fiscal periods, units, and semantic predicates with regex and NLP patterns. High recall is prioritized so borderline sentences are kept for the comparison stage to evaluate.
- **Deterministic normalization** — currency expressions (`₹12.5 crore`, `$4.2 billion`, `12.5%`) are converted to canonical `Decimal` values so exact numeric comparison is possible without an LLM.
- **MiniLM + FAISS** — `all-MiniLM-L6-v2` embeds each fact locally. FAISS retrieves semantically similar candidates without comparing every fact against every other fact.
- **Deterministic comparison first** — most relationships (corroboration, contradiction, contextual reconciliation) are resolved without an LLM using subject, predicate, time period, scope, geography, and normalized value checks.
- **LLM Router** — `LLMRouter` tries Groq first and falls back to Gemini automatically for the small number of ambiguous pairs. Both providers implement the same interface so the pipeline does not depend on either SDK directly.
- **Evidence grounding** — every fact carries an exact source quote, readable document filename, page number, chunk ID, and character offsets. Quotes that cannot be located on their source page are marked `EVIDENCE_FAILED` rather than silently accepted.
- **Cross-document relationships** — matching subject and predicate facts are compared across documents even when embedding similarity misses the candidate, producing corroboration, contradiction, reconciliation, or ambiguity results with both source facts attached.
- **Supabase as source of truth** — documents, pages, chunks, facts, evidence, and relationships are stored in PostgreSQL. FAISS is a replaceable retrieval index that can be rebuilt from stored facts.
- **Dynamic schema** — facts use a flexible `subject / predicate / value / qualifiers` shape. New predicates are extracted without adding hard-coded metric types, so the system generalizes to new documents.

### AI Tools Used

- Google Gemini (`gemini-3.7-flash`, with `gemini-3.6-flash` fallback) — relationship reasoning fallback
- Groq (`openai/gpt-oss-20b`) — primary relationship reasoning provider
- `sentence-transformers/all-MiniLM-L6-v2` — local semantic embeddings
- GitHub Copilot — initial scaffolding; architecture and all logic reviewed and completed manually

---

## Limitations and Next Steps

- **OCR** — image-only or scanned pages are detected and flagged but not processed. Integrating Tesseract or a hosted OCR API would fix this.
- **Tables** — PDF tables are extracted as flat text, which reduces structured numeric extraction quality. A dedicated table parser (pdfplumber, Camelot) would help significantly.
- **Entity resolution** — "ABC Ltd", "ABC Limited", and "ABC" are treated as different subjects. A lightweight alias resolver would improve cross-document corroboration.
- **FAISS persistence** — the index is rebuilt in memory on each restart. Persisting and reloading it would make incremental processing truly seamless.
- **Frontend pagination** — all facts and relationships load at once; pagination is needed for large document collections.

Next steps: OCR, table extraction, entity resolution, FAISS persistence, incremental processing without a restart.

---

## Additional Notes

- The starter PDFs are not committed to the repository (they are gitignored).
- No credentials are stored in the repository; all keys are loaded from `.env` at runtime.
- The system works without Supabase (in-memory fallback) and without LLM keys (ambiguous pairs are marked `AMBIGUOUS`) so evaluators can run it with minimal setup.
- The `MemoryStore` in-memory fallback loses data on restart; configure Supabase for a durable deployment.
