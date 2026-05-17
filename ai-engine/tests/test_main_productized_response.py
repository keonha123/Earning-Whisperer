from __future__ import annotations

from fastapi.testclient import TestClient

import main


class _FakeResult:
    def model_dump(self) -> dict:
        return {
            'direction': 'BEARISH',
            'magnitude': 0.61,
            'confidence': 0.78,
            'rationale': 'Demand commentary softened and management was evasive.',
            'catalyst_type': 'DEMAND_DOWN',
            'strategy': 'REVERSAL_CATALYST',
            'hold_days': 2,
            'risk_flags': ['short_squeeze_risk'],
            'metadata': {
                'trade_plan': {
                    'entry_style': 'sell_rip_or_breakdown',
                    'stop_loss': 104.0,
                    'time_stop_days': 2,
                    'sizing_hint': 'micro_size',
                    'execution_notes': ['초기 반등 실패 확인 후 진입'],
                },
                'signal_explanation': {
                    'display_text': '수요 둔화와 evasive Q&A가 확인되어 약세 시그널입니다.',
                    'summary_ko': '실적 발표 이후 하방 변동성 확대 가능성이 높은 Short 후보입니다.',
                    'key_factors_ko': ['수요 언급 둔화', 'Q&A 회피 증가'],
                    'counterfactors_ko': ['숏커버링 반등 가능성'],
                    'hold_period_reason_ko': '초기 1~2거래일 내 방향성이 가장 강하게 반영될 가능성이 높습니다.',
                },
                'transcript_signals': {
                    'topic_deltas': {'guidance': -0.12, 'demand': -0.26, 'margin': -0.08, 'capex': 0.01},
                    'confidence_signal': -0.22,
                    'evasion_score': 0.31,
                    'contradiction_penalty': -0.11,
                },
                'product_surface': {
                    'schema_version': '2026-04-19.product-surface.v1',
                    'actionability_score': 0.74,
                    'recommended_primary_surface': 'decision_unlock',
                    'front_payload_ko': {
                        'primary_surface': {'code': 'decision_unlock', 'title': '건별 의사결정 Unlock', 'reason': '즉시 판단형'},
                        'secondary_surfaces': [],
                        'unlock_cards': [{'code': 'decision_card', 'title': '의사결정 카드'}],
                        'summary': '즉시 판단형 신호입니다.',
                    },
                    'frontend_contract_ko': {
                        'hero': {'title': 'Short 후보', 'badge': '중확신'},
                        'cta': {'primary': {'action_code': 'unlock_decision_card', 'label': '판단 열기'}},
                    },
                },
            },
        }


async def _fake_run_analysis(**kwargs):
    return _FakeResult()


def test_analyze_endpoint_returns_legacy_and_productized_payload(monkeypatch) -> None:
    monkeypatch.setattr(main.app.state.analysis_service, 'analyze', _fake_run_analysis)
    client = TestClient(main.app)

    resp = client.post(
        '/v1/engine/analyze',
        json={
            'ticker': 'TSLA',
            'prompt': 'Demand looks softer in Europe and margins are under pressure.',
            'section_type': 'Q_AND_A',
            'source_type': 'EARNINGS_CALL',
            'chunk_sequence': 1,
            'market_data': {'current_price': 100.0, 'gap_pct': -2.0, 'surprise_pct': -4.0, 'volume_ratio': 2.1, 'iv_rank': 66.0},
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['status'] == 'ok'
    assert payload['strategy'] == 'REVERSAL_CATALYST'
    assert payload['analysis']['direction'] == 'BEARISH'
    assert payload['data']['event']['ticker'] == 'TSLA'
    assert payload['data']['analysis']['topic_deltas']['demand_delta'] == -0.26
    assert any(card['card_type'] == 'hero_decision' for card in payload['data']['cards'])
    assert payload['data']['paywall']['primary_surface']['code'] == 'decision_unlock'
