from __future__ import annotations

import json
from pathlib import Path

from repositories.event_store_repository import EventStoreRepository


class _FakeExecutor:
    def __init__(self) -> None:
        self.statements = []
        self.script = None
        self.executed = None
        self.executed_params = None
        self.fetch_one_result = None
        self.fetch_all_result = []

    def execute_transaction(self, statements):
        self.statements = statements

    def execute_script(self, sql_script: str) -> None:
        self.script = sql_script

    def execute(self, query: str, params=None) -> None:
        self.executed = query
        self.executed_params = params

    def fetch_one(self, query: str, params=None):
        return self.fetch_one_result

    def fetch_all(self, query: str, params=None):
        return self.fetch_all_result


SAMPLE_ENVELOPE = {
    'request_id': 'req_tsla_20260419T120000Z_001',
    'timestamp': '2026-04-19T12:00:00Z',
    'status': 'ok',
    'schema_version': '2026-04-19.ai-engine-event-v1',
    'strategy': 'REVERSAL_CATALYST',
    'analysis': {
        'direction': 'BEARISH',
        'magnitude': 0.61,
        'confidence': 0.78,
        'rationale': 'Demand commentary softened and management was evasive.',
        'catalyst_type': 'DEMAND_DOWN',
        'strategy': 'REVERSAL_CATALYST',
        'hold_days': 2,
        'review_triggered': True,
        'model_version': 'gemini-3.1-pro-preview',
        'metadata': {
            'trade_plan': {
                'entry_style': 'sell_rip_or_breakdown',
                'stop_loss': 104.0,
                'take_profit_1': 97.0,
                'take_profit_2': 94.0,
                'time_stop_days': 2,
                'sizing_hint': 'micro_size',
                'execution_notes': ['초기 반등 실패 확인 후 진입'],
            },
            'transcript_signals': {
                'topic_deltas': {'guidance': -0.12, 'demand': -0.26, 'margin': -0.08, 'capex': 0.01},
            },
        },
    },
    'metadata': {
        'trade_plan': {
            'entry_style': 'sell_rip_or_breakdown',
            'stop_loss': 104.0,
            'take_profit_1': 97.0,
            'take_profit_2': 94.0,
            'time_stop': 'D+2 종가 기준 재평가',
            'positioning_note': '초기 반등 실패 확인 후 진입 / micro_size',
            'invalidation': '104.0 이탈 시 시나리오 약화',
        },
        'transcript_signals': {
            'topic_deltas': {'guidance': -0.12, 'demand': -0.26, 'margin': -0.08, 'capex': 0.01},
        },
    },
    'data': {
        'event': {
            'event_id': 'evt_tsla_2026q2_001',
            'ticker': 'TSLA',
            'company_name': 'Tesla',
            'event_type': 'earnings_call',
            'event_time': '2026-04-19T12:00:00Z',
            'market_session': 'post_market',
            'sector': 'Automotive',
            'schema_version': '2026-04-19.ai-engine-event-v1',
        },
        'market_snapshot': {
            'current_price': 100.0,
            'gap_pct': -2.0,
            'surprise_pct': -4.0,
            'volume_ratio': 2.1,
        },
        'analysis': {
            'direction': 'BEARISH',
            'magnitude': 0.61,
            'confidence': 0.78,
            'catalyst_type': 'DEMAND_DOWN',
            'strategy_decision': {
                'strategy': 'REVERSAL_CATALYST',
                'score': 0.74,
                'hold_days': 2,
                'rationale': '실적 이후 하방 반응 지속 가능성',
                'risk_flags': ['short_squeeze_risk'],
            },
            'signal_explanation': {
                'display_text': '수요 둔화와 evasive Q&A가 확인되어 약세 시그널입니다.',
                'summary_ko': '실적 발표 이후 하방 변동성 확대 가능성이 높은 Short 후보입니다.',
                'reasons': ['수요 언급 둔화', 'Q&A 회피 증가'],
                'risks': ['숏커버링 반등 가능성'],
                'counter_scenario': '초기 약세가 이어지지 않으면 숏 시나리오가 약해질 수 있습니다.',
                'hold_period_reason': '초기 1~2거래일 내 방향성이 가장 강하게 반영될 가능성이 높습니다.',
            },
            'topic_deltas': {
                'guidance_delta': -0.12,
                'demand_delta': -0.26,
                'margin_delta': -0.08,
                'capex_delta': 0.01,
            },
        },
        'cards': [
            {
                'card_id': 'card_hero_evt_tsla_2026q2_001',
                'card_type': 'hero_decision',
                'priority': 1,
                'visible': True,
                'locked': False,
                'payload': {'headline': '수요 언급 둔화', 'summary': 'Short 후보'},
            },
            {
                'card_id': 'card_trade_evt_tsla_2026q2_001',
                'card_type': 'trade_plan',
                'priority': 3,
                'visible': True,
                'locked': True,
                'payload': {
                    'strategy': 'REVERSAL_CATALYST',
                    'strategy_label_ko': '반전 촉매',
                    'entry_style': 'sell_rip_or_breakdown',
                    'entry_style_label_ko': '반등 매도 또는 하향 이탈 진입',
                    'entry_zone': '99.0~101.0',
                    'take_profit_1': 97.0,
                    'take_profit_2': 94.0,
                    'invalidation': '104.0 이탈 시 시나리오 약화',
                    'time_stop': 'D+2 종가 기준 재평가',
                    'positioning_note': '초기 반등 실패 확인 후 진입 / micro_size',
                },
                'lock_context': {'paywall_type': 'decision_unlock'},
            },
        ],
        'paywall': {
            'primary_surface': {'code': 'decision_unlock', 'title': '건별 의사결정 Unlock'},
            'secondary_surfaces': [],
            'unlock_cards': [{'code': 'decision_card'}],
            'frontend_contract_ko': {'hero': {'title': 'Short 후보'}},
            'summary': '즉시 판단형 신호입니다.',
        },
        'replay': {
            'status': 'tracking',
            'original_signal': {'decision': 'short_candidate', 'strategy': 'REVERSAL_CATALYST', 'hold_days': 2},
            'milestones': [{'day': 'D+1', 'status': 'pending'}],
            'expected_path': '초기 1~2거래일 내 방향성이 가장 강하게 반영될 가능성이 높습니다.',
            'exit_watch': '초기 약세가 이어지지 않으면 숏 시나리오가 약해질 수 있습니다.',
        },
    },
}


def test_repository_builds_postgres_insert_plan(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.save_event_envelope(SAMPLE_ENVELOPE)

    assert result.persisted is True
    assert result.event_id == 'evt_tsla_2026q2_001'
    assert result.run_id.startswith('run_')
    assert result.row_counts['ai_cards'] == 2
    assert len(executor.statements) == 9

    analysis_stmt = executor.statements[1]
    assert 'insert into ai_analysis_runs' in analysis_stmt[0]
    assert analysis_stmt[1]['strategy_code'] == 'REVERSAL_CATALYST'
    assert analysis_stmt[1]['hold_days'] == 2

    feature_stmt = executor.statements[2]
    topic_deltas = json.loads(feature_stmt[1]['topic_deltas_json'])
    assert topic_deltas['demand_delta'] == -0.26

    replay_stmt = executor.statements[-1]
    assert 'insert into ai_replay_tracks' in replay_stmt[0]
    assert 'on conflict (run_id) do update set' in replay_stmt[0]


def test_repository_bootstrap_reads_schema_file(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('create table demo(id int);', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.bootstrap_schema()

    assert result.applied is True
    assert executor.script == 'create table demo(id int);'


def test_repository_schema_enforces_replay_run_id_uniqueness() -> None:
    schema_path = Path(__file__).resolve().parents[1] / 'sql' / 'ai_engine_event_store_schema.sql'
    sql_script = schema_path.read_text(encoding='utf-8')

    assert 'ai_replay_tracks_run_id_key' in sql_script
    assert 'add constraint ai_replay_tracks_run_id_key unique (run_id)' in sql_script
    assert 'partition by run_id' in sql_script
    assert 'delete from ai_replay_tracks target' in sql_script


def test_repository_updates_replay_track_with_partial_patch(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.sql"
    schema_path.write_text("select 1;", encoding="utf-8")
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.update_replay_track(
        "run_demo",
        {
            "status": "closed",
            "realized_pnl_pct": 3.2,
            "milestones": [{"day": "D+2", "status": "hit_tp1"}],
            "close_reason": "tp1_hit",
        },
    )

    assert result.updated is True
    assert result.run_id == "run_demo"
    assert "update ai_replay_tracks" in executor.executed
    assert executor.executed_params["status"] == "closed"
    assert executor.executed_params["close_reason"] == "tp1_hit"
    assert "hit_tp1" in executor.executed_params["milestones"]


def test_repository_lists_runs_with_pagination(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_one_result = {'total': 2}
    executor.fetch_all_result = [
        {'run_id': 'run_1', 'event_id': 'evt_1', 'ticker': 'TSLA', 'strategy_code': 'REVERSAL_CATALYST'},
        {'run_id': 'run_2', 'event_id': 'evt_2', 'ticker': 'AAPL', 'strategy_code': 'POST_EARNINGS_DRIFT'},
    ]
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.list_runs(limit=2, offset=0, ticker='TSLA')

    assert result['pagination']['total'] == 2
    assert result['filters']['ticker'] == 'TSLA'
    assert len(result['items']) == 2


def test_repository_builds_metrics_overview(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    calls = {'n': 0}
    def _fetch_one(query: str, params=None):
        calls['n'] += 1
        return {
            'total_runs': 10,
            'ok_runs': 9,
            'closed_replays': 4,
            'winning_replays': 3,
            'avg_confidence': 0.77,
            'avg_realized_pnl_pct': 2.4,
            'avg_mfe_pct': 3.1,
            'avg_mae_pct': -1.2,
        }
    def _fetch_all(query: str, params=None):
        if 'group by r.strategy_code' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 3, 'avg_confidence': 0.8, 'avg_realized_pnl_pct': 2.8}]
        return [{'ticker': 'TSLA', 'runs': 4, 'avg_confidence': 0.78, 'avg_realized_pnl_pct': 2.1}]
    executor.fetch_one = _fetch_one
    executor.fetch_all = _fetch_all

    result = repo.get_metrics_overview(lookback_days=30)

    assert result['lookback_days'] == 30
    assert result['summary']['win_rate_pct'] == 75.0
    assert result['by_strategy'][0]['win_rate_pct'] == 75.0
    assert result['top_tickers'][0]['ticker'] == 'TSLA'


def test_repository_builds_quality_scorecard(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_one_result = {
        'total_runs': 10,
        'explanation_coverage_count': 9,
        'trade_plan_coverage_count': 10,
        'replay_coverage_count': 8,
        'replay_closed_count': 4,
        'review_triggered_count': 2,
        'low_confidence_count': 3,
        'avg_confidence': 0.72,
    }
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.get_quality_scorecard(lookback_days=30)

    assert result['lookback_days'] == 30
    assert result['rates']['explanation_coverage_pct'] == 90.0
    assert result['rates']['replay_closed_rate_pct'] == 40.0


def test_repository_builds_strategy_drift(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    def _fetch_all(query: str, params=None):
        if 'where r.created_at >= now() - make_interval(days => %(short_window_days)s)' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 5, 'closed_replays': 4, 'wins': 1, 'avg_realized_pnl_pct': -1.5}]
        return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 12, 'closed_replays': 8, 'wins': 6, 'avg_realized_pnl_pct': 2.8}]
    executor.fetch_all = _fetch_all

    result = repo.get_strategy_drift(short_window_days=7, baseline_window_days=30)

    assert result['short_window_days'] == 7
    assert result['degrading'][0]['strategy_code'] == 'REVERSAL_CATALYST'
    assert result['degrading'][0]['diagnosis'] == 'degrading'


def test_repository_builds_strategy_leaderboard(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_all_result = [
        {'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 3, 'avg_confidence': 0.81, 'avg_realized_pnl_pct': 2.9},
        {'strategy_code': 'POST_EARNINGS_DRIFT', 'runs': 8, 'closed_replays': 5, 'wins': 4, 'avg_confidence': 0.77, 'avg_realized_pnl_pct': 1.2},
    ]
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    result = repo.get_strategy_leaderboard(lookback_days=30, limit=5, min_closed=1, metric='avg_realized_pnl_pct')

    assert result['items'][0]['rank'] == 1
    assert result['items'][0]['strategy_code'] == 'REVERSAL_CATALYST'


def test_repository_builds_control_recommendations(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    def _fetch_one(query: str, params=None):
        return {
            'total_runs': 10,
            'explanation_coverage_count': 8,
            'trade_plan_coverage_count': 10,
            'replay_coverage_count': 8,
            'replay_closed_count': 4,
            'review_triggered_count': 2,
            'low_confidence_count': 3,
            'avg_confidence': 0.71,
        }
    def _fetch_all(query: str, params=None):
        if 'order by r.strategy_code asc' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_confidence': 0.72, 'avg_realized_pnl_pct': -2.7}]
        if 'where r.created_at >= now() - make_interval(days => %(short_window_days)s)' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_realized_pnl_pct': -2.7}]
        return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 12, 'closed_replays': 8, 'wins': 6, 'avg_realized_pnl_pct': 2.8}]
    executor.fetch_one = _fetch_one
    executor.fetch_all = _fetch_all

    result = repo.get_control_recommendations(short_window_days=7, baseline_window_days=30, lookback_days=30)

    assert result['recommendations'][0]['strategy_code'] == 'REVERSAL_CATALYST'
    assert result['recommendations'][0]['action'] == 'soft_disable'


def test_repository_builds_gate_tuning_recommendations(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    def _fetch_one(query: str, params=None):
        return {
            'total_runs': 10,
            'explanation_coverage_count': 8,
            'trade_plan_coverage_count': 10,
            'replay_coverage_count': 8,
            'replay_closed_count': 4,
            'review_triggered_count': 2,
            'low_confidence_count': 3,
            'avg_confidence': 0.71,
        }
    def _fetch_all(query: str, params=None):
        if 'order by r.strategy_code asc' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_confidence': 0.72, 'avg_realized_pnl_pct': -2.7}]
        if 'where r.created_at >= now() - make_interval(days => %(short_window_days)s)' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_realized_pnl_pct': -2.7}]
        return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 12, 'closed_replays': 8, 'wins': 6, 'avg_realized_pnl_pct': 2.8}]
    executor.fetch_one = _fetch_one
    executor.fetch_all = _fetch_all

    result = repo.get_gate_tuning_recommendations(short_window_days=7, baseline_window_days=30, lookback_days=30)

    assert result['items'][0]['strategy_code'] == 'REVERSAL_CATALYST'
    assert result['items'][0]['suggested_gate_patch']['min_confidence_delta'] == 0.1


def test_repository_evaluates_alerts(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)

    def _fetch_one(query: str, params=None):
        return {
            'total_runs': 10,
            'explanation_coverage_count': 8,
            'trade_plan_coverage_count': 10,
            'replay_coverage_count': 8,
            'replay_closed_count': 4,
            'review_triggered_count': 2,
            'low_confidence_count': 3,
            'avg_confidence': 0.71,
        }
    def _fetch_all(query: str, params=None):
        if 'order by r.strategy_code asc' in query:
            return [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_confidence': 0.72, 'avg_realized_pnl_pct': -2.7}]
        if 'where r.created_at >= now() - make_interval(days => %(short_window_days)s)' in query:
            return [
                {'strategy_code': 'REVERSAL_CATALYST', 'runs': 6, 'closed_replays': 4, 'wins': 1, 'avg_realized_pnl_pct': -2.7},
                {'strategy_code': 'POST_EARNINGS_DRIFT', 'runs': 5, 'closed_replays': 4, 'wins': 2, 'avg_realized_pnl_pct': -1.0},
            ]
        return [
            {'strategy_code': 'REVERSAL_CATALYST', 'runs': 12, 'closed_replays': 8, 'wins': 6, 'avg_realized_pnl_pct': 2.8},
            {'strategy_code': 'POST_EARNINGS_DRIFT', 'runs': 10, 'closed_replays': 8, 'wins': 6, 'avg_realized_pnl_pct': 1.5},
        ]
    executor.fetch_one = _fetch_one
    executor.fetch_all = _fetch_all

    result = repo.evaluate_alerts(short_window_days=7, baseline_window_days=30, lookback_days=30)

    assert result['alert_count'] >= 2
    codes = {x['code'] for x in result['alerts']}
    assert 'EXPLANATION_COVERAGE_LOW' in codes
    assert 'SOFT_DISABLE_RECOMMENDED' in codes


def test_repository_applies_gate_patch(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_one_result = {'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'patch_json': {'min_confidence_delta': 0.05}, 'rationale_ko': '테스트'}
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)
    result = repo.apply_gate_patch(1, actor='pm')
    assert result['active_patch_id'] == 1
    assert result['applied'] is True


def test_repository_lists_active_gate_configs(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_all_result = [{'strategy_code': 'REVERSAL_CATALYST', 'active_patch_id': 1, 'patch_json': {'min_confidence_delta': 0.05}}]
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)
    result = repo.list_active_gate_configs(strategy_code='REVERSAL_CATALYST', limit=10, offset=0)
    assert result['items'][0]['active_patch_id'] == 1


def test_repository_rolls_back_active_gate_config(tmp_path: Path) -> None:
    schema_path = tmp_path / 'schema.sql'
    schema_path.write_text('select 1;', encoding='utf-8')
    executor = _FakeExecutor()
    executor.fetch_one_result = {'patch_id': 2, 'strategy_code': 'REVERSAL_CATALYST', 'patch_json': {'min_confidence_delta': 0.02}, 'rationale_ko': 'rollback'}
    repo = EventStoreRepository(executor=executor, schema_path=schema_path)
    result = repo.rollback_active_gate_config('REVERSAL_CATALYST', target_patch_id=2, actor='pm')
    assert result['active_patch_id'] == 2
    assert result['action'] == 'rollback_to_patch'
