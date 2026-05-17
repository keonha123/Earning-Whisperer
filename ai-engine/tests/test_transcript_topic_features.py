from __future__ import annotations

from core.transcript_signal_enhancer import TranscriptSignalEnhancer
from models.request_models import SectionType
from models.signal_models import GeminiAnalysisResult


def test_transcript_topic_deltas_capture_guidance_and_demand_shift() -> None:
    enhancer = TranscriptSignalEnhancer(window=4)
    base = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.72,
        confidence=0.8,
        rationale='Demand was healthy and margin improved.',
        catalyst_type='EARNINGS_BEAT',
    )

    enhancer.evaluate(
        ticker='NVDA',
        text_chunk='Demand was healthy. Gross margin expansion continued. Guidance unchanged.',
        section_type=SectionType.GUIDANCE,
        analysis=base,
    )
    snap = enhancer.evaluate(
        ticker='NVDA',
        text_chunk='We are raising guidance. Healthy demand improved and bookings accelerated.',
        section_type=SectionType.GUIDANCE,
        analysis=base,
    )

    assert snap.topic_deltas['guidance'] > 0
    assert snap.topic_deltas['demand'] > 0
    assert 'topic_deltas' in snap.to_dict()
