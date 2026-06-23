from __future__ import annotations

from pathlib import Path

from models.evidence_models import EvidenceBackend, EvidenceDocument, EvidenceRetrievalRequest, EvidenceSourceType
from repositories.evidence_store_repository import EvidenceStoreRepository


class FakeExecutor:
    def __init__(self) -> None:
        self.transactions = []
        self.scripts = []
        self.rows = []

    def execute_transaction(self, statements):
        self.transactions.append(statements)

    def execute_script(self, sql_script):
        self.scripts.append(sql_script)

    def execute(self, query, params=None):
        return None

    def fetch_one(self, query, params=None):
        return None

    def fetch_all(self, query, params=None):
        return list(self.rows)


def test_postgres_evidence_repository_persists_and_reloads(tmp_path: Path) -> None:
    executor = FakeExecutor()
    schema = tmp_path / "schema.sql"
    schema.write_text("create table test(id int);", encoding="utf-8")
    repository = EvidenceStoreRepository(
        backend=EvidenceBackend.PGVECTOR,
        executor=executor,
        schema_path=schema,
    )
    document = EvidenceDocument(
        document_id="nvda-filing",
        ticker="NVDA",
        source_type=EvidenceSourceType.FILING,
        source="SEC 10-Q",
        title="Quarterly filing",
        content="Data center demand remained strong and gross margin improved.",
        reliability_score=0.95,
    )

    assert repository.bootstrap_schema() is True
    assert repository.add_documents([document]) == 1
    assert executor.scripts
    assert executor.transactions

    executor.rows = [
        {
            "document_id": "nvda-filing",
            "ticker": "NVDA",
            "source_type": "FILING",
            "source_name": "SEC 10-Q",
            "title": "Quarterly filing",
            "published_at": None,
            "source_url": None,
            "content": "Data center demand remained strong and gross margin improved.",
            "reliability_score": 0.95,
            "metadata_json": {},
        }
    ]
    fresh = EvidenceStoreRepository(backend=EvidenceBackend.PGVECTOR, executor=executor)
    result = fresh.search(EvidenceRetrievalRequest(ticker="NVDA", query="data center gross margin"))

    assert result.evidence
    assert result.evidence[0].document_id == "nvda-filing"
    assert not any(item.startswith("postgres_evidence_fallback") for item in result.warnings)
