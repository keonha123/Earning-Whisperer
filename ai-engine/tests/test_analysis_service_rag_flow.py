from __future__ import annotations

import json
import time

import pytest

from core.analysis_service import AnalysisService
from core.external_retriever import ExternalDocument
from core.gemini_client import GenerationUsage
from models.request_models import MarketData, SectionType, SourceType


@pytest.mark.asyncio
async def test_analysis_service_injects_external_rag_evidence(monkeypatch) -> None:
    service = AnalysisService()
    service.external_retriever.reset_backend()
    service.external_retriever.clear()
    now = int(time.time())
    service.external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="nvda-evidence",
                ticker="NVDA",
                title="NVDA guidance update",
                text="NVIDIA raised data center guidance because AI accelerator demand remained strong.",
                published_at=now - 30,
                source_type="news",
                importance=0.9,
            )
        ]
    )
    captured: dict[str, str] = {}

    async def _fake_generate_content_with_metadata(*, model, contents=None, prompt=None, config):
        captured["prompt"] = contents or prompt or ""
        return GenerationUsage(
            text=json.dumps(
                {
                    "direction": "BULLISH",
                    "magnitude": 0.62,
                    "confidence": 0.78,
                    "rationale": "Guidance and demand language are positive.",
                    "catalyst_type": "GUIDANCE_RAISE",
                    "euphemism_count": 0,
                    "negative_word_ratio": 0.0,
                }
            ),
            prompt_tokens=120,
            output_tokens=30,
            total_tokens=150,
        )

    monkeypatch.setattr("core.analysis_service.gemini_client.generate_content_with_metadata", _fake_generate_content_with_metadata)

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Management raised guidance and said AI demand and data center margin remain strong.",
        market_data=MarketData(ticker="NVDA", current_price=900.0, volume_ratio=2.2, gap_pct=4.0),
        section_type=SectionType.Q_AND_A,
        source_type=SourceType.EARNINGS_CALL,
        chunk_sequence=1,
        request_priority=9,
        is_final=False,
    )

    assert "EXTERNAL_EVIDENCE" in captured["prompt"]
    assert "NVIDIA raised data center guidance" in captured["prompt"]
    assert result.metadata["external_rag"]["has_external_evidence"] is True
    assert result.metadata["external_rag"]["evidence_count"] >= 1
