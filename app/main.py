from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .api.store import MemoryStore
from .db.repository import SupabaseRepository
from .db.writer import SupabaseWriter
from .ingestion import ExtractionError, extract_pages
from .llm.fact_extractor import FactExtractor
from .llm.gemini_client import GeminiClient
from .pipeline import ProcessingPipeline, fact_to_dict
from .retrieval.embeddings import FactEmbedder, VectorIndex

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or ["http://localhost:5173"]


def build_default_pipeline() -> ProcessingPipeline:
    return ProcessingPipeline(
        extractor=FactExtractor(GeminiClient()),
        vector_index=VectorIndex(FactEmbedder()),
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
    if os.getenv("SUPABASE_DB_URL"):
        app.state.writer = SupabaseWriter(SupabaseRepository())
    # Explicit stores are used by fast API tests; the real default app processes uploads.
    app.state.pipeline = pipeline if pipeline is not None else (build_default_pipeline() if store is None else None)

    @app.post("/documents/upload", status_code=202)
    async def upload_document(file: UploadFile = File(...)):
        filename = Path(file.filename or "upload.pdf").name
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=415, detail="Only PDF files are accepted")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="PDF exceeds the 20 MB upload limit")
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="Uploaded file is not a valid PDF")

        document_id = str(uuid4())
        file_hash = hashlib.sha256(content).hexdigest()
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
                temporary_path = temporary_file.name
                temporary_file.write(content)
                temporary_file.flush()
            pages = extract_pages(temporary_path, document_id)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if temporary_path:
                os.unlink(temporary_path)

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
        if app.state.pipeline is not None:
            try:
                result = app.state.pipeline.process(pages)
            except Exception as exc:
                app.state.store.add_processing_error(document_id, str(exc))
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
            app.state.store.add_processing_result(
                document_id,
                [fact_to_dict(fact) | {"document_id": document_id} for fact in result.facts],
                relationship_rows,
                "COMPLETED" if not result.failures else "COMPLETED_WITH_ERRORS",
            )
            for failure in result.failures:
                app.state.store.add_processing_error(document_id, f"{failure.stage}: {failure.message}")
            if app.state.writer is not None:
                try:
                    app.state.writer.persist(document, pages, result)
                except Exception as exc:
                    app.state.store.add_processing_error(document_id, f"supabase_persistence: {exc}")
        return app.state.store.documents[document_id]

    @app.get("/documents")
    def list_documents():
        return list(app.state.store.documents.values())

    @app.get("/documents/{document_id}")
    def get_document(document_id: str):
        document = app.state.store.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {**document, "pages": app.state.store.pages.get(document_id, [])}

    @app.get("/documents/{document_id}/facts")
    def document_facts(document_id: str):
        if document_id not in app.state.store.documents:
            raise HTTPException(status_code=404, detail="Document not found")
        return [fact for fact in app.state.store.facts if fact.get("document_id") == document_id]

    @app.get("/facts")
    def list_facts():
        return app.state.store.facts

    @app.get("/facts/{fact_id}")
    def get_fact(fact_id: str):
        for fact in app.state.store.facts:
            if fact.get("id") == fact_id:
                return fact
        raise HTTPException(status_code=404, detail="Fact not found")

    @app.get("/relationships")
    def list_relationships():
        return app.state.store.relationships

    @app.get("/relationships/{relationship_id}")
    def get_relationship(relationship_id: str):
        for relationship in app.state.store.relationships:
            if relationship.get("id") == relationship_id:
                return relationship
        raise HTTPException(status_code=404, detail="Relationship not found")

    @app.get("/knowledge-layer")
    def knowledge_layer():
        return app.state.store.knowledge_layer()

    @app.get("/processing-errors")
    def processing_errors():
        return app.state.store.errors

    @app.get("/processing/{document_id}")
    def processing_status(document_id: str):
        document = app.state.store.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "status": document["status"]}

    return app


app = create_app()