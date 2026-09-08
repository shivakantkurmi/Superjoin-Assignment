from io import BytesIO

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