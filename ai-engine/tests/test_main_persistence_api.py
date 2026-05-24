from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from tests.test_event_store_repository import SAMPLE_ENVELOPE


class _FakeResult:
    def model_dump(self) -> dict:
        return SAMPLE_ENVELOPE['analysis']


async def _fake_run_analysis(**kwargs):
    return _FakeResult()


class _FakeRepository:
    def __init__(self) -> None:
        self.last_envelope = None
        self.bootstrapped = False
        self.last_patch = None

    def save_event_envelope(self, envelope):
        self.last_envelope = envelope
        return SimpleNamespace(
            persisted=True,
            event_id=envelope['data']['event']['event_id'],
            run_id='run_fake123',
            row_counts={'ai_events': 1, 'ai_cards': len(envelope['data']['cards'])},
        )



    def list_runs(self, **kwargs):
        return {
            'items': [{'run_id': 'run_fake123', 'ticker': 'TSLA', 'strategy_code': 'REVERSAL_CATALYST'}],
            'pagination': {'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0), 'returned': 1, 'total': 1},
            'filters': kwargs,
        }




    def get_gate_tuning_recommendations(self, **kwargs):
        return {
            'short_window_days': kwargs.get('short_window_days', 7),
            'baseline_window_days': kwargs.get('baseline_window_days', 30),
            'lookback_days': kwargs.get('lookback_days', 30),
            'items': [{'strategy_code': 'REVERSAL_CATALYST', 'suggested_gate_patch': {'min_confidence_delta': 0.05}}],
        }

    def evaluate_alerts(self, **kwargs):
        return {
            'short_window_days': kwargs.get('short_window_days', 7),
            'baseline_window_days': kwargs.get('baseline_window_days', 30),
            'lookback_days': kwargs.get('lookback_days', 30),
            'alerts': [{'severity': 'high', 'code': 'SOFT_DISABLE_RECOMMENDED'}],
            'alert_count': 1,
            'action_counts': {'soft_disable': 1},
        }

    def get_strategy_leaderboard(self, **kwargs):
        return {
            'lookback_days': kwargs.get('lookback_days', 30),
            'metric': kwargs.get('metric', 'avg_realized_pnl_pct'),
            'min_closed': kwargs.get('min_closed', 3),
            'limit': kwargs.get('limit', 10),
            'items': [{'rank': 1, 'strategy_code': 'REVERSAL_CATALYST', 'avg_realized_pnl_pct': 3.2, 'closed_replays': 4}],
        }

    def get_control_recommendations(self, **kwargs):
        return {
            'scorecard': {'lookback_days': kwargs.get('lookback_days', 30)},
            'drift': {'short_window_days': kwargs.get('short_window_days', 7)},
            'leaderboard_metric': 'avg_realized_pnl_pct',
            'recommendations': [{'strategy_code': 'REVERSAL_CATALYST', 'action': 'tighten_gate'}],
            'action_counts': {'tighten_gate': 1},
        }

    def get_quality_scorecard(self, **kwargs):
        return {
            'lookback_days': kwargs.get('lookback_days', 30),
            'summary': {'total_runs': 10, 'avg_confidence': 0.74},
            'rates': {'explanation_coverage_pct': 90.0, 'trade_plan_coverage_pct': 100.0, 'replay_closed_rate_pct': 50.0},
        }

    def get_strategy_drift(self, **kwargs):
        return {
            'short_window_days': kwargs.get('short_window_days', 7),
            'baseline_window_days': kwargs.get('baseline_window_days', 30),
            'items': [{'strategy_code': 'REVERSAL_CATALYST', 'diagnosis': 'degrading'}],
            'degrading': [{'strategy_code': 'REVERSAL_CATALYST', 'diagnosis': 'degrading'}],
            'improving': [],
            'stable': [],
        }

    def get_metrics_overview(self, **kwargs):
        return {
            'lookback_days': kwargs.get('lookback_days', 30),
            'summary': {'total_runs': 12, 'closed_replays': 5, 'winning_replays': 3, 'win_rate_pct': 60.0},
            'by_strategy': [{'strategy_code': 'REVERSAL_CATALYST', 'runs': 8, 'closed_replays': 4, 'wins': 3, 'win_rate_pct': 75.0}],
            'top_tickers': [{'ticker': 'TSLA', 'runs': 4, 'avg_confidence': 0.78}],
        }

    def get_run_bundle(self, run_id):
        return {
            'run_id': run_id,
            'event': SAMPLE_ENVELOPE['data']['event'],
            'analysis_run': {'run_id': run_id, 'strategy_code': 'REVERSAL_CATALYST'},
            'cards': SAMPLE_ENVELOPE['data']['cards'],
            'replay': SAMPLE_ENVELOPE['data']['replay'],
        }

    def get_event_bundle(self, event_id):
        return {
            'event': SAMPLE_ENVELOPE['data']['event'],
            'runs': [{'run_id': 'run_fake123', 'strategy_code': 'REVERSAL_CATALYST'}],
        }

    def save_gate_patch(self, payload):
        return {
            'patch_id': 1,
            'strategy_code': payload['strategy_code'],
            'patch_json': payload['patch'],
            'applied': payload.get('applied', False),
            'status': payload.get('status', 'draft'),
            'approval_state': payload.get('approval_state', 'pending'),
            'audit_trail_count': 1,
            'active_rollout_id': None,
        }

    def list_gate_patches(self, **kwargs):
        return {'items': [{'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST'}], 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def get_gate_patch(self, patch_id):
        return {
            'patch_id': patch_id,
            'strategy_code': 'REVERSAL_CATALYST',
            'patch_json': {'min_confidence_delta': 0.05},
            'status': 'approved',
            'approval_state': 'approved',
            'scope_type': 'strategy_global',
        }

    def save_patch_audit_log(self, **kwargs):
        return {'audit_id': 1, **kwargs}

    def get_gate_patch_audit(self, patch_id):
        return {
            'patch': self.get_gate_patch(patch_id),
            'approvals': [{'decision': 'approved'}],
            'audit_trail': [{'event_type': 'patch_created'}, {'event_type': 'patch_approved'}],
            'audit_trail_count': 2,
        }

    def approve_gate_patch(self, patch_id, **kwargs):
        result = self.get_gate_patch(patch_id)
        result.update({'status': 'approved', 'approval_state': 'approved', 'audit_trail_count': 2})
        return result

    def reject_gate_patch(self, patch_id, **kwargs):
        result = self.get_gate_patch(patch_id)
        result.update({'status': 'rejected', 'approval_state': 'rejected', 'audit_trail_count': 2})
        return result

    def save_alert_state_action(self, payload):
        return {'action_id': 1, 'code': payload['code'], 'status': payload['status'], 'scope': payload.get('scope', 'global')}

    def list_alert_state_actions(self, **kwargs):
        return {'items': [{'action_id': 1, 'code': 'SOFT_DISABLE_RECOMMENDED', 'status': 'acknowledged'}], 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def apply_gate_patch(self, patch_id, actor=None):
        return {
            'strategy_code': 'REVERSAL_CATALYST',
            'active_patch_id': patch_id,
            'patch_json': {'min_confidence_delta': 0.05},
            'updated_by': actor,
            'applied': True,
            'status': 'prod_active',
            'approval_state': 'approved',
        }

    def list_active_gate_configs(self, **kwargs):
        return {'items': [{'strategy_code': 'REVERSAL_CATALYST', 'active_patch_id': 1}], 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def rollback_active_gate_config(self, strategy_code, target_patch_id, actor=None):
        return {'strategy_code': strategy_code, 'active_patch_id': target_patch_id, 'patch_json': {'min_confidence_delta': 0.02}, 'updated_by': actor, 'action': 'rollback_to_patch'}

    def find_latest_patch(self, **kwargs):
        return {'patch_id': 2, 'strategy_code': kwargs.get('strategy_code', 'REVERSAL_CATALYST')}

    def create_rollout(self, **kwargs):
        return {'rollout_id': 1, 'patch_id': kwargs['patch_id'], 'strategy_code': 'REVERSAL_CATALYST', 'current_stage_pct': kwargs.get('initial_stage_pct', 10), 'status': 'canary_active', 'report_id': kwargs.get('report_id')}

    def list_rollouts(self, **kwargs):
        status = kwargs.get('status')
        items = [{'rollout_id': 1, 'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'current_stage_pct': 10, 'status': 'canary_active', 'report_id': 'report_demo'}]
        if status == 'active':
            return {'items': items, 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}
        return {'items': items, 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def get_rollout(self, rollout_id):
        return {'rollout_id': rollout_id, 'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'current_stage_pct': 10, 'status': 'canary_active', 'report_id': 'report_demo'}

    def save_rollout_stage_event(self, **kwargs):
        return {'stage_event_id': 1, **kwargs}

    def advance_rollout(self, **kwargs):
        return {'rollout_id': kwargs['rollout_id'], 'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'current_stage_pct': kwargs['to_stage_pct'], 'status': 'staged_active', 'report_id': kwargs.get('report_id')}

    def abort_rollout(self, rollout_id, **kwargs):
        return {'rollout_id': rollout_id, 'status': 'aborted'}

    def set_control_state(self, **kwargs):
        return {'control_state_id': 1, **kwargs}

    def list_control_states(self, **kwargs):
        return {'items': [], 'limit': kwargs.get('limit', 100), 'offset': kwargs.get('offset', 0)}

    def get_effective_control_states(self, **kwargs):
        return []

    def resolve_active_patch(self, **kwargs):
        return None

    def normalize_market_cap_bucket(self, market_cap):
        return 'large'

    def materialize_thresholds(self, **kwargs):
        return {
            'min_confidence': 0.55,
            'min_composite': 0.45,
            'min_raw_score': 0.35,
            'min_volume_ratio': 1.0,
            'min_event_quality': 0.35,
            'max_gap_overshoot': 3.0,
            'position_scale_delta': 0.0,
            'max_hold_days_delta': 0.0,
        }

    def extract_event_quality(self, analysis):
        return 0.5

    def compute_gap_overshoot(self, market_data):
        return 0.0

    def save_regression_report(self, payload):
        self.saved_report = payload
        return {
            'report_id': payload['report_id'],
            'suite_name': payload['suite_name'],
            'strategy_code': payload['strategy_code'],
            'overall': payload['overall'],
            'verdict': payload['verdict'],
            'promotion_recommendation': payload['promotion_recommendation'],
            'closed_replay_sample': payload['closed_replay_sample'],
        }

    def get_regression_report(self, report_id):
        return {
            'report_id': report_id,
            'suite_name': 'prod_guardrail_core',
            'strategy_code': 'REVERSAL_CATALYST',
            'overall': {
                'score': 4.1,
                'closed_replay_sample': 90,
                'comparison': {'avg_return_delta_bps': 6.0, 'false_positive_delta': -0.03},
            },
            'verdict': 'pass',
            'promotion_recommendation': 'promote_candidate',
        }

    def list_regression_reports(self, **kwargs):
        return {'items': [self.get_regression_report('report_demo')], 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def get_closed_replay_samples(self, **kwargs):
        return [
            {'ticker': 'TSLA', 'sector': 'AUTO', 'sector_code': 'AUTO', 'market_cap_bucket': 'large', 'regime': 'normal', 'event_time': f'2026-04-{day:02d}', 'confidence': 0.8, 'strategy_score': 0.7, 'magnitude': 0.6, 'volume_ratio': 2.0, 'event_quality': 0.6, 'gap_overshoot': 0.0, 'realized_pnl_pct': 0.03 if day % 2 else -0.01, 'mfe_pct': 0.05, 'mae_pct': -0.02, 'hold_days': 2, 'milestones': [{'day': 'D+1', 'status': 'tp1_hit'}]}
            for day in range(1, 45)
        ]

    def save_hold_tuning_snapshot(self, **kwargs):
        return {'snapshot_id': 1, **kwargs}

    def compute_hold_tuning_snapshot(self, rows):
        return {'expected_mfe_mae_ratio': 2.0, 'time_to_peak_ewma': 1.0, 'time_to_fail_ewma': 2.0, 'sample_size': len(rows)}

    def save_calibration_proposal(self, payload):
        return {'proposal_id': 1, **payload, 'promoted': False}

    def list_calibration_proposals(self, **kwargs):
        return {'items': [{'proposal_id': 1, 'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'segment_type': 'global', 'segment_key': 'all'}], 'limit': kwargs.get('limit', 20), 'offset': kwargs.get('offset', 0)}

    def get_calibration_proposal(self, proposal_id):
        return {'proposal_id': proposal_id, 'patch_id': 1, 'strategy_code': 'REVERSAL_CATALYST', 'segment_type': 'global', 'segment_key': 'all'}

    def mark_calibration_proposal_promoted(self, proposal_id, **kwargs):
        return {'proposal_id': proposal_id, 'promoted': True}

    def update_replay_track(self, run_id, patch):
        self.last_patch = (run_id, patch)
        return SimpleNamespace(updated=True, run_id=run_id, fields_updated=sorted(patch.keys()))

    def bootstrap_schema(self):
        self.bootstrapped = True
        return SimpleNamespace(applied=True, schema_path='sql/ai_engine_event_store_schema.sql')


def test_persist_endpoint_accepts_engine_envelope(monkeypatch) -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.post('/v1/engine/events/persist', json=SAMPLE_ENVELOPE)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['persisted'] is True
    assert payload['event_id'] == 'evt_tsla_2026q2_001'
    assert fake_repo.last_envelope['data']['event']['ticker'] == 'TSLA'


def test_analyze_and_persist_endpoint_returns_envelope_and_storage(monkeypatch) -> None:
    async def _fake_dispatch(payload):
        return SAMPLE_ENVELOPE

    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo
    monkeypatch.setattr(main.app.state, 'dispatch_analysis', _fake_dispatch)

    resp = client.post(
        '/v1/engine/analyze-and-persist',
        json={
            'ticker': 'TSLA',
            'prompt': 'Demand looks softer in Europe and margins are under pressure.',
            'section_type': 'Q_AND_A',
            'source_type': 'EARNINGS_CALL',
            'chunk_sequence': 1,
            'market_data': {'current_price': 100.0, 'gap_pct': -2.0, 'surprise_pct': -4.0, 'volume_ratio': 2.1},
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['persisted'] is True
    assert payload['run_id'] == 'run_fake123'
    assert payload['envelope']['data']['analysis']['direction'] == 'BEARISH'
    assert payload['envelope']['data']['event']['ticker'] == 'TSLA'


def test_bootstrap_schema_endpoint(monkeypatch) -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.post('/v1/engine/admin/bootstrap-schema')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['applied'] is True
    assert fake_repo.bootstrapped is True


def test_get_run_bundle_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/runs/run_fake123')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['run_id'] == 'run_fake123'
    assert payload['bundle']['analysis_run']['strategy_code'] == 'REVERSAL_CATALYST'


def test_get_event_bundle_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/events/evt_tsla_2026q2_001')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['event_id'] == 'evt_tsla_2026q2_001'
    assert payload['bundle']['runs'][0]['run_id'] == 'run_fake123'


def test_patch_replay_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.patch(
        '/v1/engine/replay/run_fake123',
        json={'status': 'closed', 'realized_pnl_pct': 3.1, 'close_reason': 'tp1_hit'},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['updated'] is True
    assert payload['fields_updated'] == ['close_reason', 'realized_pnl_pct', 'status']
    assert fake_repo.last_patch[0] == 'run_fake123'
    assert fake_repo.last_patch[1]['close_reason'] == 'tp1_hit'


def test_list_runs_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/runs?limit=10&offset=0&ticker=TSLA')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['pagination']['total'] == 1
    assert payload['result']['items'][0]['ticker'] == 'TSLA'


def test_metrics_overview_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/metrics/overview?lookback_days=45')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['lookback_days'] == 45
    assert payload['result']['summary']['win_rate_pct'] == 60.0


def test_quality_scorecard_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/metrics/scorecard?lookback_days=21')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['lookback_days'] == 21
    assert payload['result']['rates']['explanation_coverage_pct'] == 90.0


def test_strategy_drift_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/metrics/drift?short_window_days=5&baseline_window_days=25')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['short_window_days'] == 5
    assert payload['result']['degrading'][0]['diagnosis'] == 'degrading'


def test_strategy_leaderboard_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/metrics/leaderboard?metric=avg_realized_pnl_pct&min_closed=1&limit=5')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['items'][0]['rank'] == 1
    assert payload['result']['items'][0]['strategy_code'] == 'REVERSAL_CATALYST'


def test_control_recommendations_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/controls/recommendations?short_window_days=5&baseline_window_days=20&lookback_days=20')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['recommendations'][0]['action'] == 'tighten_gate'
    assert payload['result']['action_counts']['tighten_gate'] == 1


def test_gate_tuning_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/controls/gate-tuning?short_window_days=5&baseline_window_days=20&lookback_days=20')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['items'][0]['suggested_gate_patch']['min_confidence_delta'] == 0.05


def test_alert_evaluation_endpoint() -> None:
    client = TestClient(main.app)
    fake_repo = _FakeRepository()
    main.app.state.event_store_repository = fake_repo

    resp = client.get('/v1/engine/alerts/evaluate?short_window_days=5&baseline_window_days=20&lookback_days=20')

    assert resp.status_code == 200
    payload = resp.json()
    assert payload['result']['alert_count'] == 1
    assert payload['result']['alerts'][0]['code'] == 'SOFT_DISABLE_RECOMMENDED'


def test_create_gate_patch_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.post('/v1/engine/controls/gate-patches', json={'strategy_code': 'REVERSAL_CATALYST', 'patch': {'min_confidence_delta': 0.05}, 'rationale_ko': '테스트', 'source': 'manual', 'applied': False, 'created_by': 'pm'})
    assert resp.status_code == 200
    assert resp.json()['result']['strategy_code'] == 'REVERSAL_CATALYST'


def test_list_gate_patches_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.get('/v1/engine/controls/gate-patches?strategy_code=REVERSAL_CATALYST')
    assert resp.status_code == 200
    assert resp.json()['result']['items'][0]['strategy_code'] == 'REVERSAL_CATALYST'


def test_create_alert_state_action_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.post('/v1/engine/alerts/state-actions', json={'code': 'SOFT_DISABLE_RECOMMENDED', 'scope': 'global', 'status': 'acknowledged', 'note': 'ok', 'actor': 'pm'})
    assert resp.status_code == 200
    assert resp.json()['result']['status'] == 'acknowledged'


def test_list_alert_state_actions_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.get('/v1/engine/alerts/state-actions?code=SOFT_DISABLE_RECOMMENDED')
    assert resp.status_code == 200
    assert resp.json()['result']['items'][0]['code'] == 'SOFT_DISABLE_RECOMMENDED'


def test_apply_gate_patch_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.post('/v1/engine/controls/gate-patches/1/apply', json={'actor': 'pm'})
    assert resp.status_code == 200
    assert resp.json()['result']['active_patch_id'] == 1


def test_list_active_gate_configs_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.get('/v1/engine/controls/gate-configs?strategy_code=REVERSAL_CATALYST')
    assert resp.status_code == 200
    assert resp.json()['result']['items'][0]['strategy_code'] == 'REVERSAL_CATALYST'


def test_rollback_active_gate_config_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    resp = client.post('/v1/engine/controls/gate-configs/REVERSAL_CATALYST/rollback', json={'target_patch_id': 2, 'actor': 'pm'})
    assert resp.status_code == 200
    assert resp.json()['result']['active_patch_id'] == 2


def test_shadow_compare_gate_patch_endpoint() -> None:
    client = TestClient(main.app)
    payload = {'strategy_code': 'REVERSAL_CATALYST', 'baseline': {'hit_rate': 0.52, 'avg_return_bps': 18.0, 'max_drawdown_bps': 42.0, 'false_positive_rate': 0.14, 'sample_size': 100}, 'candidate': {'hit_rate': 0.57, 'avg_return_bps': 24.0, 'max_drawdown_bps': 36.0, 'false_positive_rate': 0.11, 'sample_size': 90}}
    resp = client.post('/v1/engine/controls/gate-patches/shadow-compare', json=payload)
    assert resp.status_code == 200
    assert resp.json()['result']['decision'] == 'promote'


def test_gate_auto_promotion_evaluate_endpoint() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()
    payload = {'strategy_code': 'REVERSAL_CATALYST', 'target_patch_id': 1, 'baseline': {'hit_rate': 0.52, 'avg_return_bps': 18.0, 'max_drawdown_bps': 42.0, 'false_positive_rate': 0.14, 'sample_size': 100}, 'candidate': {'hit_rate': 0.57, 'avg_return_bps': 24.0, 'max_drawdown_bps': 36.0, 'false_positive_rate': 0.11, 'sample_size': 90}, 'policy': {'min_score': 3.0, 'min_sample_size': 30, 'require_positive_avg_return_delta': True, 'max_false_positive_delta': 0.0, 'auto_apply': True}, 'actor': 'pm'}
    resp = client.post('/v1/engine/controls/gate-patches/auto-promotion/evaluate', json=payload)
    assert resp.status_code == 200
    assert resp.json()['result']['decision'] == 'promote_candidate'
    assert resp.json()['result']['action'] == 'auto_applied'
