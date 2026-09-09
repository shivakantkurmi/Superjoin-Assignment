from io import BytesIO

try:
    import pymupdf as fitz
except ImportError:
    import fitz
from fastapi.testclient import TestClient

from app.api.store import MemoryStore
from app.main import create_app


def pdf_bytes(text: str = "Revenue for FY2024 was INR 125 crore.") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_pdf_upload_extracts_pages_and_exposes_status():
    client = TestClient(create_app(MemoryStore()))
    response = client.post(
        "/documents/upload",
        files={"file": ("report.pdf", BytesIO(pdf_bytes()), "application/pdf")},
    )

    assert response.status_code == 202
    document = response.json()
    assert document["page_count"] == 1
    assert document["status"] == "PROCESSING"
    assert client.get(f"/processing/{document['id']}").json()["status"] == "PROCESSING"
    assert client.get(f"/documents/{document['id']}").json()["pages"][0]["page_number"] == 1


def test_upload_rejects_non_pdf_content():
    client = TestClient(create_app(MemoryStore()))
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", BytesIO(b"not a pdf"), "text/plain")},
    )
    assert response.status_code == 415


def test_upload_pipeline_failure_records_error_and_marks_failed():
    class FailingPipeline:
        def process(self, pages):
            raise RuntimeError("sentence-transformers is not installed")

    class RecordingRepo:
        def __init__(self):
            self.inserts = []
            self.updates = []

        def insert(self, table, values):
            self.inserts.append((table, values))

        def update(self, table, row_id, values):
            self.updates.append((table, row_id, values))

        def fetch_all(self, table):
            return []

    from app.db.writer import SupabaseWriter
    store = MemoryStore()
    app = create_app(store, pipeline=FailingPipeline())
    repo = RecordingRepo()
    app.state.writer = SupabaseWriter(repo)

    client = TestClient(app)
    response = client.post(
        "/documents/upload",
        files={"file": ("report.pdf", BytesIO(pdf_bytes()), "application/pdf")},
    )

    assert response.status_code == 502
    assert "Document processing failed" in response.json()["detail"]

    # Verify document was inserted BEFORE processing_errors was inserted
    table_names = [table for table, _ in repo.inserts]
    assert table_names == ["documents", "processing_errors"]

    doc_id = repo.inserts[0][1]["id"]
    error_doc_id = repo.inserts[1][1]["document_id"]
    assert doc_id == error_doc_id

    # Verify document was marked as FAILED
    assert store.documents[doc_id]["status"] == "FAILED"
    assert ("documents", doc_id, {"status": "FAILED"}) in repo.updates