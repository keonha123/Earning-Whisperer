from __future__ import annotations

from fastapi.testclient import TestClient

import main
from config import Settings
from core.external_retriever import InMemoryExternalRetriever
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


def test_company_and_transcript_ingestion_api(tmp_path) -> None:
    app = main.create_app()
    company_repository = CompanyIntelligenceRepository(store_path=tmp_path / "company.json")
    company_service = CompanyIntelligenceService(company_repository)
    evidence_service = EvidenceRetrievalService(
        repository=EvidenceStoreRepository(),
        company_repository=company_repository,
    )
    ingestion = EvidenceIngestionService(
        settings=Settings(external_chunk_size_chars=600),
        evidence_service=evidence_service,
        external_retriever=RetrieverFacadeStub(),
        company_service=company_service,
    )
    app.state.company_intelligence_service = company_service
    app.state.company_intelligence_repository = company_repository
    app.state.evidence_service = evidence_service
    app.state.evidence_ingestion_service = ingestion
    client = TestClient(app)

    upsert = client.post(
        "/v1/engine/company-intelligence/upsert",
        json={
            "ticker": "NVDA",
            "relationships": [
                {
                    "source_ticker": "NVDA",
                    "target_ticker": "TSMC",
                    "relationship": "supplier/foundry",
                    "strength": 0.8,
                    "reason_ko": "파운드리 수요 연쇄효과",
                }
            ],
        },
    )
    transcript = client.post(
        "/v1/engine/transcripts/ingest",
        json={
            "ticker": "NVDA",
            "title": "Q1 call",
            "text": "Jensen Huang -- President and Chief Executive Officer\nWe raised guidance as demand improved.",
        },
    )
    company = client.get("/v1/engine/company-intelligence/NVDA")

    assert upsert.status_code == 200
    assert transcript.status_code == 200
    assert transcript.json()["speakers"][0]["is_executive"] is True
    assert company.status_code == 200
    assert company.json()["relationships"][0]["target_ticker"] == "TSMC"
    assert company.json()["executives"][0]["is_ceo"] is True
