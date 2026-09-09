from app.extraction.chunking import chunk_pages, clean_text
from app.models import Page


def test_cleaning_and_chunking_preserve_page_context():
    page = Page("doc-1", 3, "Revenue was INR 125 crore.\nIt increased year-over-year.")
    chunks = chunk_pages([page], max_characters=40)
    assert chunks[0].page_number == 3
    assert "Revenue was INR 125 crore." in chunks[0].text
    assert clean_text("a  b\n c") == "a b c"
