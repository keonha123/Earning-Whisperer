from __future__ import annotations

from pathlib import Path

from models.intelligence_models import CompanyIntelligenceUpsertRequest, ExecutiveProfile, ImpactRelationshipRecord
from repositories.company_intelligence_repository import CompanyIntelligenceRepository
from services.company_intelligence_service import CompanyIntelligenceService


def test_company_intelligence_is_data_driven_and_durable(tmp_path: Path) -> None:
    store = tmp_path / "company.json"
    service = CompanyIntelligenceService(CompanyIntelligenceRepository(store_path=store))
    service.upsert(
        CompanyIntelligenceUpsertRequest(
            ticker="META",
            relationships=[
                ImpactRelationshipRecord(
                    source_ticker="META",
                    target_ticker="NVDA",
                    relationship="AI infrastructure supplier",
                    strength=0.71,
                    reason_ko="AI 투자 확대가 GPU 수요에 영향을 줄 수 있습니다.",
                )
            ],
            executives=[
                ExecutiveProfile(
                    executive_id="meta-ceo",
                    ticker="META",
                    name="Example Executive",
                    current_role="Chief Executive Officer",
                    is_ceo=True,
                    career_history=["Founder"],
                    achievements=["Scaled the company"],
                )
            ],
        )
    )

    reloaded = CompanyIntelligenceService(CompanyIntelligenceRepository(store_path=store)).get("META")
    assert reloaded.relationships[0].target_ticker == "NVDA"
    assert reloaded.executives[0].achievements == ["Scaled the company"]


def test_company_intelligence_is_injected_into_rag_documents(tmp_path: Path) -> None:
    from models.request_models import MarketData, SourceType
    from repositories.evidence_store_repository import EvidenceStoreRepository
    from services.evidence_retrieval_service import EvidenceRetrievalService

    repository = CompanyIntelligenceRepository(store_path=tmp_path / "company-rag.json")
    repository.upsert_executives(
        [
            ExecutiveProfile(
                executive_id="nvda-ceo",
                ticker="NVDA",
                name="Example CEO",
                current_role="Chief Executive Officer",
                is_ceo=True,
                achievements=["Expanded data center revenue"],
                leadership_traits=["disciplined capital allocation"],
                confidence=0.8,
            )
        ]
    )
    service = EvidenceRetrievalService(
        repository=EvidenceStoreRepository(),
        company_repository=repository,
    )

    result = service.retrieve_for_analysis(
        ticker="NVDA",
        current_chunk="Management discussed disciplined capital allocation and data center expansion.",
        source_type=SourceType.EARNINGS_CALL,
        market_data=MarketData(),
        canonical_bundle=None,
        source_health=[],
        request_metadata={},
        evidence_documents=[],
    )

    assert any(item.source == "company_intelligence.executive_profile" for item in result.evidence)
