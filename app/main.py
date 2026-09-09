from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

try:
    from dotenv import load_dotenv

    load_dotenv()
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

from .api.store import MemoryStore
from .db.repository import SupabaseRepository
from .db.writer import SupabaseWriter
from .extraction.candidate_facts import DeterministicFactExtractor
from .ingestion import ExtractionError, extract_pages
from .llm.gemini_client import GeminiClient  # noqa: F401 – kept for tests that import it directly
from .llm.providers import GeminiProvider, GroqProvider, LLMRouter
from .llm.relationship_reasoner import RelationshipReasoner
from .pipeline import ProcessingPipeline, fact_to_dict
from .retrieval.embeddings import FactEmbedder, VectorIndex

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB – supports 100+ page PDFs
logger = logging.getLogger(__name__)


def cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    # Include both default Vite ports so dev server works without configuring .env
    return origins or ["http://localhost:5173", "http://localhost:5174"]


def build_default_pipeline() -> ProcessingPipeline:
    embedder = FactEmbedder()
    # Prefer the available Groq provider; Gemini remains a fallback for transient outages.
    router = LLMRouter([GroqProvider(), GeminiProvider(GeminiClient())])
    return ProcessingPipeline(
        extractor=DeterministicFactExtractor(),
        vector_index=VectorIndex(embedder),
        reasoner=RelationshipReasoner(router),
    )


def create_app(store: MemoryStore | None = None, pipeline: ProcessingPipeline | None = None) -> FastAPI:
    app = FastAPI(title="Fact Knowledge Layer", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store or MemoryStore()
    app.state.writer = None
    if os.getenv("SUPABASE_DB_URL") and store is None:
        app.state.writer = SupabaseWriter(SupabaseRepository())
    # Explicit stores are used by fast API tests; the real default app processes uploads.
    app.state.pipeline = pipeline if pipeline is not None else (build_default_pipeline() if store is None else None)

    def persistent_rows(table: str) -> list[dict] | None:
        """Fetch from Supabase; return None if the DB is unreachable."""
        if app.state.writer is None:
            return None
        try:
            return app.state.writer.repository.fetch_all(table)
        except Exception as exc:
            logger.warning("supabase fetch_all table=%s failed (falling back to memory): %s", table, exc)
            return None

    def public_facts() -> list[dict]:
        """Return facts from Supabase if available; fall back to the in-memory store."""
        rows = persistent_rows("facts")
        if rows is None:
            documents = {str(doc["id"]): doc.get("filename", "document") for doc in app.state.store.documents.values()}
            return [
                {
                    **fact,
                    "evidence": (
                        {**fact["evidence"], "document_name": documents.get(str(fact["evidence"].get("document_id")), "document")}
                        if fact.get("evidence")
                        else None
                    ),
                }
                for fact in app.state.store.facts
            ]
        if not rows:
            return []
        documents = {str(row["id"]): row.get("filename", "document") for row in (persistent_rows("documents") or [])}
        pages = {str(row["id"]): row for row in (persistent_rows("pages") or [])}
        evidence = {
            str(row["fact_id"]): {
                "document_id": str(row["document_id"]),
                "document_name": documents.get(str(row["document_id"]), "document"),
                "page_number": pages.get(str(row["page_id"]), {}).get("page_number"),
                "chunk_id": row.get("chunk_id"),
                "quote": row["quote"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "verification_status": row["verification_status"],
            }
            for row in (persistent_rows("evidence") or [])
        }
        return [
            {
                "id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "subject": row["subject"],
                "predicate": row["predicate"],
                "value": row["object_value"],
                "normalized_value": row["normalized_value"],
                "unit": row["unit"],
                "time": {"label": row["time_label"]} if row["time_label"] else {},
                "scope": row["scope"],
                "location": row["location"],
                "qualifiers": row["qualifiers"],
                "confidence": float(row["confidence"]),
                "status": row["status"],
                "evidence": evidence.get(str(row["id"])),
            }
            for row in rows
        ]

    def public_relationships() -> list[dict]:
        """Return relationships with the two source facts and their evidence."""
        rows = persistent_rows("relationships")
        relationships = rows if rows is not None else app.state.store.relationships
        facts_by_id = {str(fact["id"]): fact for fact in public_facts()}
        return [
            {
                **relationship,
                "fact_a": facts_by_id.get(str(relationship.get("fact_a_id"))),
                "fact_b": facts_by_id.get(str(relationship.get("fact_b_id"))),
            }
            for relationship in relationships
        ]

    def record_processing_error(document_id: str, message: str, stage: str = "processing") -> None:
        app.state.store.add_processing_error(document_id, message)
        if app.state.writer is not None:
            try:
                app.state.writer.repository.insert(
                    "processing_errors",
                    {
                        "document_id": document_id,
                        "stage": stage,
                        "error_type": "PIPELINE",
                        "message": message,
                    },
                )
            except Exception as exc:
                logger.warning("supabase processing_error insert failed: %s", exc)

    @app.post("/documents/upload", status_code=202)
    async def upload_document(file: UploadFile = File(...)):
        filename = Path(file.filename or "upload.pdf").name
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=415, detail="Only PDF files are accepted")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="PDF exceeds the 50 MB upload limit")
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="Uploaded file is not a valid PDF")

        document_id = str(uuid4())
        file_hash = hashlib.sha256(content).hexdigest()

        # Check for existing document with same file_hash (e.g. re-uploading a failed or updated document)
        existing_doc = None
        if app.state.writer is not None:
            try:
                rows = persistent_rows("documents") or []
                existing_doc = next((r for r in rows if r.get("file_hash") == file_hash), None)
            except Exception:
                pass
        if existing_doc is None:
            existing_doc = next(
                (d for d in app.state.store.documents.values() if d.get("file_hash") == file_hash),
                None,
            )

        if existing_doc is not None:
            document_id = str(existing_doc["id"])
            if app.state.writer is not None:
                try:
                    with app.state.writer.repository.connect().cursor() as cur:
                        cur.execute("delete from documents where id = %s", [document_id])
                    app.state.writer.repository.connect().commit()
                except Exception as exc:
                    logger.warning("failed to delete previous document %s: %s", document_id, exc)
            app.state.store.documents.pop(document_id, None)
            app.state.store.pages.pop(document_id, None)
            app.state.store.facts = [f for f in app.state.store.facts if str(f.get("document_id")) != document_id]

        try:
            pages = extract_pages(content, document_id)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        document = {
            "id": document_id,
            "filename": filename,
            "file_hash": file_hash,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "PROCESSING",
            "page_count": len(pages),
            "facts_count": 0,
            "relationships_count": 0,
        }
        page_rows = [
            {
                "document_id": page.document_id,
                "page_number": page.page_number,
                "text": page.text,
                "is_scanned": page.is_scanned,
            }
            for page in pages
        ]
        app.state.store.add_document(document, page_rows)
        logger.info("document id=%s stage=pdf_extraction pages=%d status=completed", document_id, len(pages))

        # Insert document record upfront so foreign key references (e.g. processing_errors) succeed
        if app.state.writer is not None:
            try:
                app.state.writer.repository.insert("documents", document)
            except Exception as exc:
                logger.warning("supabase document insert failed: %s", exc)

        if app.state.pipeline is not None:
            try:
                logger.info("document id=%s stage=processing status=started", document_id)
                result = app.state.pipeline.process(pages)
            except Exception as exc:
                record_processing_error(document_id, str(exc))
                app.state.store.documents[document_id]["status"] = "FAILED"
                if app.state.writer is not None:
                    try:
                        app.state.writer.repository.update("documents", document_id, {"status": "FAILED"})
                    except Exception as update_exc:
                        logger.warning("supabase document status update failed: %s", update_exc)
                raise HTTPException(status_code=502, detail=f"Document processing failed: {exc}") from exc
            relationship_rows = [
                {
                    "fact_a_id": fact_a_id,
                    "fact_b_id": fact_b_id,
                    "relationship_type": relationship.relationship_type.value,
                    "confidence": relationship.confidence,
                    "explanation": relationship.explanation,
                    "factors": list(relationship.factors),
                }
                for fact_a_id, fact_b_id, relationship in result.relationships
            ]
            final_status = "COMPLETED" if not result.failures else "COMPLETED_WITH_ERRORS"
            app.state.store.add_processing_result(
                document_id,
                [fact_to_dict(fact) | {"document_id": document_id} for fact in result.facts],
                relationship_rows,
                final_status,
            )
            for failure in result.failures:
                record_processing_error(document_id, f"{failure.stage}: {failure.message}", failure.stage)
            if app.state.writer is not None:
                try:
                    app.state.writer.persist(document, pages, result)
                    # Update counts and final status on the document row
                    app.state.writer.repository.update(
                        "documents",
                        document_id,
                        {
                            "facts_count": len(result.facts),
                            "relationships_count": len(result.relationships),
                            "status": final_status,
                        },
                    )
                except Exception as exc:
                    record_processing_error(document_id, f"supabase_persistence: {exc}", "supabase_persistence")
            logger.info(
                "document id=%s stage=processing status=%s facts=%d relationships=%d",
                document_id,
                app.state.store.documents[document_id]["status"],
                len(result.facts),
                len(result.relationships),
            )
        return app.state.store.documents[document_id]
    @app.get("/health")
    def health():
        db_connected = False
        if app.state.writer is not None:
            try:
                persistent_rows("documents")
                db_connected = True
            except Exception:
                db_connected = False
        return {"status": "healthy", "database": "connected" if db_connected else "in_memory"}

    @app.get("/documents")
    def list_documents():
        rows = persistent_rows("documents")
        return rows if rows is not None else list(app.state.store.documents.values())

    @app.get("/documents/{document_id}")
    def get_document(document_id: str):
        rows = persistent_rows("documents")
        document = (
            next((row for row in rows if str(row["id"]) == document_id), None)
            if rows is not None
            else None
        ) or app.state.store.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        pages_list = persistent_rows("pages")
        pages = (
            [row for row in pages_list if str(row["document_id"]) == document_id]
            if pages_list is not None
            else []
        ) or app.state.store.pages.get(document_id, [])
        return {**document, "pages": pages}

    @app.delete("/documents/{document_id}")
    def delete_document(document_id: str):
        if app.state.writer is not None:
            try:
                with app.state.writer.repository.connect().cursor() as cur:
                    cur.execute("delete from documents where id = %s", [document_id])
                app.state.writer.repository.connect().commit()
            except Exception as exc:
                logger.warning("failed to delete document %s from DB: %s", document_id, exc)
        app.state.store.documents.pop(document_id, None)
        app.state.store.pages.pop(document_id, None)
        app.state.store.facts = [f for f in app.state.store.facts if str(f.get("document_id")) != document_id]
        if app.state.pipeline is not None:
            app.state.pipeline.remove_document(document_id)
        return {"status": "deleted", "id": document_id}

    @app.delete("/documents")
    def clear_all_documents():
        if app.state.writer is not None:
            try:
                with app.state.writer.repository.connect().cursor() as cur:
                    cur.execute("delete from documents;")
                app.state.writer.repository.connect().commit()
            except Exception as exc:
                logger.warning("failed to clear documents from DB: %s", exc)
        app.state.store.documents.clear()
        app.state.store.pages.clear()
        app.state.store.facts.clear()
        app.state.store.relationships.clear()
        app.state.store.errors.clear()
        if app.state.pipeline is not None:
            embedder = FactEmbedder()
            app.state.pipeline.vector_index = VectorIndex(embedder)
            app.state.pipeline.facts_by_id.clear()
        return {"status": "cleared"}

    @app.get("/documents/{document_id}/facts")
    def document_facts(document_id: str):
        if app.state.writer is None and document_id not in app.state.store.documents:
            raise HTTPException(status_code=404, detail="Document not found")
        return [fact for fact in public_facts() if str(fact.get("document_id")) == document_id]

    @app.get("/facts")
    def list_facts():
        return public_facts()

    @app.get("/facts/{fact_id}")
    def get_fact(fact_id: str):
        for fact in public_facts():
            if str(fact.get("id")) == fact_id:
                return fact
        raise HTTPException(status_code=404, detail="Fact not found")

    @app.get("/relationships")
    def list_relationships():
        return public_relationships()

    @app.get("/relationships/{relationship_id}")
    def get_relationship(relationship_id: str):
        rel_list = public_relationships()
        for relationship in rel_list:
            if str(relationship.get("id")) == relationship_id:
                return relationship
        raise HTTPException(status_code=404, detail="Relationship not found")

    @app.get("/knowledge-layer")
    def knowledge_layer():
        return {
            "documents": list_documents(),
            "facts": list_facts(),
            "relationships": list_relationships(),
        }

    @app.get("/processing-errors")
    def processing_errors():
        rows = persistent_rows("processing_errors")
        return rows if rows is not None else app.state.store.errors

    @app.get("/processing/{document_id}")
    def processing_status(document_id: str):
        rows = persistent_rows("documents")
        document = (
            next((row for row in rows if str(row["id"]) == document_id), None)
            if rows is not None
            else None
        ) or app.state.store.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "status": document["status"]}

    if app.state.pipeline is not None and app.state.writer is not None:
        try:
            existing = public_facts()
            if existing:
                from .models import Fact

                fact_objs = [
                    Fact(
                        id=f["id"],
                        subject=f["subject"],
                        predicate=f["predicate"],
                        object=f.get("value") or "",
                        fact_type="metric",
                        value=f.get("value"),
                        normalized_value=f.get("normalized_value"),
                        unit=f.get("unit"),
                        time=f.get("time") or {},
                        scope=f.get("scope"),
                        location=f.get("location"),
                        qualifiers=f.get("qualifiers") or {},
                        confidence=f.get("confidence", 0.5),
                        status=f.get("status", "VALID"),
                    )
                    for f in existing
                ]
                app.state.pipeline.vector_index.add_facts(fact_objs)
                app.state.pipeline.facts_by_id.update({f.id: f for f in fact_objs})
                logger.info("rehydrated %d facts into vector index from database", len(fact_objs))
        except Exception as exc:
            logger.warning("failed to rehydrate vector index from database: %s", exc)

    return app


app = create_app()