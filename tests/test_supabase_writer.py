from app.db.writer import SupabaseWriter
from app.models import Evidence, Fact, Page
from app.pipeline import ProcessingResult
from app.reasoning.relationships import RelationshipResult, RelationshipType


class RecordingRepository:
    def __init__(self):
        self.rows = []

    def insert(self, table, values):
        self.rows.append((table, values))

    def update(self, table, row_id, values):
        # update() is called by main.py after persist(); not exercised in this test
        pass


def test_writer_persists_pages_facts_evidence_and_relationships():
    """writer.persist() stores pages, chunks, facts, evidence, and relationships.

    The document row itself is inserted by main.py (the caller) *before*
    calling persist(), so writer.persist() must NOT insert a documents row.
    """
    repository = RecordingRepository()
    writer = SupabaseWriter(repository)
    document = {"id": "doc-1", "filename": "report.pdf", "file_hash": "hash", "status": "COMPLETED"}
    fact = Fact(
        id="fact-a",
        subject="abc ltd",
        predicate="revenue",
        value="125 crore",
        normalized_value=1250000000,
        fact_type="revenue",
        confidence=0.9,
        evidence=Evidence("doc-1", 1, "Revenue was 125 crore", char_start=0, char_end=21),
    )
    result = ProcessingResult(
        [fact],
        [("fact-a", "fact-b", RelationshipResult(RelationshipType.CORROBORATES, 0.9, "Values match"))],
        [],
    )

    # Simulate what main.py does: insert the document row first, then persist child rows
    repository.insert("documents", document)
    writer.persist(document, [Page("doc-1", 1, "Revenue was 125 crore")], result)

    tables = [table for table, _values in repository.rows]
    assert tables == ["documents", "pages", "chunks", "facts", "evidence", "relationships"]
    evidence_row = repository.rows[4][1]
    assert evidence_row["verification_status"] == "VERIFIED"
    assert evidence_row["page_id"]