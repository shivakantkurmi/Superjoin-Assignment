from app.db.writer import SupabaseWriter
from app.models import Evidence, Fact, Page
from app.pipeline import ProcessingResult
from app.reasoning.relationships import RelationshipResult, RelationshipType


class RecordingRepository:
    def __init__(self):
        self.rows = []

    def insert(self, table, values):
        self.rows.append((table, values))


def test_writer_persists_pages_facts_evidence_and_relationships():
    repository = RecordingRepository()
    writer = SupabaseWriter(repository)
    fact = Fact(
        id="fact-a",
        subject="abc ltd",
        predicate="revenue",
        value="125 crore",
        normalized_value=1250000000,
        fact_type="revenue",
        confidence=0.9,
        evidence=Evidence("doc-1", 1, "Revenue was 125 crore", 0, 21),
    )
    result = ProcessingResult(
        [fact],
        [("fact-a", "fact-b", RelationshipResult(RelationshipType.CORROBORATES, 0.9, "Values match"))],
        [],
    )
    writer.persist(
        {"id": "doc-1", "filename": "report.pdf", "file_hash": "hash", "status": "COMPLETED"},
        [Page("doc-1", 1, "Revenue was 125 crore")],
        result,
    )

    tables = [table for table, _values in repository.rows]
    assert tables == ["documents", "pages", "facts", "evidence", "relationships"]
    evidence = repository.rows[3][1]
    assert evidence["verification_status"] == "VERIFIED"
    assert evidence["page_id"]