from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile

from .api.store import MemoryStore
from .ingestion import ExtractionError, extract_pages
from .pipeline import ProcessingPipeline, fact_to_dict

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def create_app(store: MemoryStore | None = None, pipeline: ProcessingPipeline | None = None) -> FastAPI:
    app = FastAPI(title="Fact Knowledge Layer", version="0.1.0")
    app.state.store = store or MemoryStore()

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
        if pipeline is not None:
            result = pipeline.process(pages)
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
        return document

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

    @app.get("/processing/{document_id}")
    def processing_status(document_id: str):
        document = app.state.store.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "status": document["status"]}

    return app


app = create_app()