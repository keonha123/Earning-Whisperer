from __future__ import annotations

from pathlib import Path

from config import Settings
from core.external_retriever import InMemoryExternalRetriever
from models.intelligence_models import TranscriptIngestRequest
from repositories.company_intelligence_repository import CompanyIntelligenceRepository
from repositories.evidence_store_repository import EvidenceStoreRepository
from services.company_intelligence_service import CompanyIntelligenceService
from services.evidence_ingestion_service import EvidenceIngestionService
from services.evidence_retrieval_service import EvidenceRetrievalService


class RetrieverFacadeStub:
    def __init__(self) -> None:
        self.backend = InMemoryExternalRetriever()

    def upsert_documents(self, documents):
        return self.backend.upsert_documents(documents)

    def get_stats(self):
        return self.backend.get_stats()


def test_transcript_ingestion_persists_chunks_and_speaker_metadata(tmp_path: Path) -> None:
    company_repository = CompanyIntelligenceRepository(store_path=tmp_path / "company.json")
    company_service = CompanyIntelligenceService(company_repository)
    evidence_service = EvidenceRetrievalService(
        repository=EvidenceStoreRepository(),
        company_repository=company_repository,
    )
    ingestion = EvidenceIngestionService(
        settings=Settings(external_chunk_size_chars=600, external_chunk_overlap_chars=40),
        evidence_service=evidence_service,
        external_retriever=RetrieverFacadeStub(),
        company_service=company_service,
    )
    transcript = """Jensen Huang -- President and Chief Executive Officer
We raised guidance as data center demand remained strong and margins improved.

Colette Kress -- Executive Vice President and Chief Financial Officer
Gross margin should remain resilient despite supply constraints.
"""

    result = ingestion.ingest_transcript(
        TranscriptIngestRequest(ticker="NVDA", title="Q1 call", text=transcript, published_at="2026-05-28")
    )

    assert result.persisted >= 1
    assert result.vector_upserted >= 1
    assert {item.name for item in result.speakers} == {"Jensen Huang", "Colette Kress"}
    company = company_service.get("NVDA")
    assert len(company.executives) == 2
    assert any(item.is_ceo for item in company.executives)
