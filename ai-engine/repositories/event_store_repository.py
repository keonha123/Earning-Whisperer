from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from db.postgres_executor import BootstrapResult, SQLExecutor
except ImportError:  # pragma: no cover
    from ..db.postgres_executor import BootstrapResult, SQLExecutor


@dataclass(slots=True)
class PersistResult:
    persisted: bool
    event_id: str
    run_id: str
    row_counts: dict[str, int]


@dataclass(slots=True)
class ReplayUpdateResult:
    updated: bool
    run_id: str
    fields_updated: list[str]


class EventStoreRepository:
    def __init__(self, executor: SQLExecutor, schema_path: str | Path) -> None:
        self.executor = executor
        self.schema_path = Path(schema_path)

    def bootstrap_schema(self) -> BootstrapResult:
        sql_script = self.schema_path.read_text(encoding="utf-8")
        self.executor.execute_script(sql_script)
        return BootstrapResult(applied=True, schema_path=str(self.schema_path))

    def save_event_envelope(self, envelope: Mapping[str, Any]) -> PersistResult:
        statements, event_id, run_id, row_counts = self._build_statements(envelope)
        self.executor.execute_transaction(statements)
        return PersistResult(
            persisted=True,
            event_id=event_id,
            run_id=run_id,
            row_counts=row_counts,
        )

    def get_run_bundle(self, run_id: str) -> dict[str, Any] | None:
        analysis_run = self.executor.fetch_one(
            """
            select *
            from ai_analysis_runs
            where run_id = %(run_id)s
            """,
            {"run_id": run_id},
        )
        if not analysis_run:
            return None

        event = self.executor.fetch_one(
            """
            select *
            from ai_events
            where event_id = %(event_id)s
            """,
            {"event_id": analysis_run["event_id"]},
        )
        feature_snapshot = self.executor.fetch_one(
            "select * from ai_feature_snapshots where run_id = %(run_id)s",
            {"run_id": run_id},
        )
        signal_explanation = self.executor.fetch_one(
            "select * from ai_signal_explanations where run_id = %(run_id)s",
            {"run_id": run_id},
        )
        trade_plan = self.executor.fetch_one(
            "select * from ai_trade_plans where run_id = %(run_id)s",
            {"run_id": run_id},
        )
        paywall = self.executor.fetch_one(
            "select * from ai_paywall_surfaces where run_id = %(run_id)s",
            {"run_id": run_id},
        )
        replay = self.executor.fetch_one(
            "select * from ai_replay_tracks where run_id = %(run_id)s",
            {"run_id": run_id},
        )
        cards = self.executor.fetch_all(
            """
            select *
            from ai_cards
            where run_id = %(run_id)s
            order by priority asc, created_at asc
            """,
            {"run_id": run_id},
        )

        return {
            "run_id": run_id,
            "event": self._decode_row(event),
            "analysis_run": self._decode_row(analysis_run),
            "feature_snapshot": self._decode_row(feature_snapshot),
            "signal_explanation": self._decode_row(signal_explanation),
            "trade_plan": self._decode_row(trade_plan),
            "cards": [self._decode_row(card) for card in cards],
            "paywall": self._decode_row(paywall),
            "replay": self._decode_row(replay),
        }

    def get_event_bundle(self, event_id: str) -> dict[str, Any] | None:
        event = self.executor.fetch_one(
            "select * from ai_events where event_id = %(event_id)s",
            {"event_id": event_id},
        )
        if not event:
            return None
        runs = self.executor.fetch_all(
            """
            select run_id, event_id, direction, magnitude, confidence, catalyst_type,
                   strategy_code, hold_days, review_triggered, status, created_at
            from ai_analysis_runs
            where event_id = %(event_id)s
            order by created_at desc
            """,
            {"event_id": event_id},
        )
        return {
            "event": self._decode_row(event),
            "runs": [self._decode_row(run) for run in runs],
        }





    def get_gate_tuning_recommendations(self, *, short_window_days: int = 7, baseline_window_days: int = 30, lookback_days: int = 30) -> dict[str, Any]:
        controls = self.get_control_recommendations(short_window_days=short_window_days, baseline_window_days=baseline_window_days, lookback_days=lookback_days)
        recommendations = []
        for item in controls.get('recommendations', []):
            action = item.get('action', 'keep')
            strategy_code = item.get('strategy_code')
            recent = item.get('recent', {})
            gate_patch: dict[str, Any] = {
                'min_confidence_delta': 0.0,
                'require_review_trigger': False,
                'max_hold_days_delta': 0,
                'position_scale_delta': 0.0,
            }
            rationale = '현재 게이트를 유지할 수 있는 상태입니다.'
            if action == 'tighten_gate':
                gate_patch = {
                    'min_confidence_delta': 0.05,
                    'require_review_trigger': True,
                    'max_hold_days_delta': -1,
                    'position_scale_delta': -0.15,
                }
                rationale = '최근 성과 약화로 진입 기준을 강화하고 보유 리스크를 줄이는 편이 합리적입니다.'
            elif action == 'soft_disable':
                gate_patch = {
                    'min_confidence_delta': 0.10,
                    'require_review_trigger': True,
                    'max_hold_days_delta': -2,
                    'position_scale_delta': -0.50,
                }
                rationale = '최근 손익과 승률 저하 폭이 커서 사실상 중단에 가까운 강한 축소가 필요합니다.'
            elif action == 'expand':
                gate_patch = {
                    'min_confidence_delta': -0.03,
                    'require_review_trigger': False,
                    'max_hold_days_delta': 1,
                    'position_scale_delta': 0.10,
                }
                rationale = '최근 성과 개선이 확인되어 적용 범위를 소폭 확대할 수 있습니다.'
            recommendations.append({
                'strategy_code': strategy_code,
                'current_action': action,
                'recent': recent,
                'suggested_gate_patch': gate_patch,
                'rationale_ko': rationale,
            })
        return {
            'short_window_days': short_window_days,
            'baseline_window_days': baseline_window_days,
            'lookback_days': lookback_days,
            'items': recommendations,
        }

    def evaluate_alerts(self, *, short_window_days: int = 7, baseline_window_days: int = 30, lookback_days: int = 30) -> dict[str, Any]:
        scorecard = self.get_quality_scorecard(lookback_days=lookback_days)
        controls = self.get_control_recommendations(short_window_days=short_window_days, baseline_window_days=baseline_window_days, lookback_days=lookback_days)
        rates = scorecard.get('rates', {})
        action_counts = controls.get('action_counts', {})
        alerts: list[dict[str, Any]] = []

        explanation_cov = rates.get('explanation_coverage_pct')
        replay_closed_rate = rates.get('replay_closed_rate_pct')
        if explanation_cov is not None and explanation_cov < 95.0:
            alerts.append({
                'severity': 'medium',
                'code': 'EXPLANATION_COVERAGE_LOW',
                'title': '설명 커버리지 저하',
                'message_ko': f'설명 생성 커버리지가 {explanation_cov:.1f}%로 낮습니다. 프론트 노출 품질 점검이 필요합니다.',
                'scope': 'global',
            })
        if replay_closed_rate is not None and replay_closed_rate < 50.0:
            alerts.append({
                'severity': 'medium',
                'code': 'REPLAY_CLOSED_RATE_LOW',
                'title': '리플레이 종료율 저하',
                'message_ko': f'리플레이 종료율이 {replay_closed_rate:.1f}%입니다. 사후 성과 추적 누락 가능성을 점검해야 합니다.',
                'scope': 'global',
            })
        if action_counts.get('soft_disable', 0) > 0:
            alerts.append({
                'severity': 'high',
                'code': 'SOFT_DISABLE_RECOMMENDED',
                'title': '전략 중단 권고 발생',
                'message_ko': f"soft_disable 권고 전략이 {action_counts.get('soft_disable', 0)}개 있습니다. 운영 검토가 필요합니다.",
                'scope': 'strategy',
            })
        if action_counts.get('tighten_gate', 0) >= 2:
            alerts.append({
                'severity': 'medium',
                'code': 'MULTI_STRATEGY_DEGRADING',
                'title': '복수 전략 성능 악화',
                'message_ko': f"gate 강화 권고 전략이 {action_counts.get('tighten_gate', 0)}개입니다. 시장 환경 적합성 재점검이 필요합니다.",
                'scope': 'strategy',
            })
        return {
            'short_window_days': short_window_days,
            'baseline_window_days': baseline_window_days,
            'lookback_days': lookback_days,
            'alerts': alerts,
            'alert_count': len(alerts),
            'action_counts': action_counts,
        }

    def get_strategy_leaderboard(self, *, lookback_days: int = 30, limit: int = 10, min_closed: int = 3, metric: str = "avg_realized_pnl_pct") -> dict[str, Any]:
        allowed_metrics = {"avg_realized_pnl_pct", "win_rate_pct", "avg_confidence"}
        if metric not in allowed_metrics:
            raise ValueError(f"Unsupported leaderboard metric: {metric}")
        rows = self.executor.fetch_all(
            """
            select
                r.strategy_code,
                count(*) as runs,
                count(*) filter (where rp.status = 'closed') as closed_replays,
                count(*) filter (where rp.status = 'closed' and coalesce(rp.realized_pnl_pct, 0) > 0) as wins,
                avg(r.confidence) as avg_confidence,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct
            from ai_analysis_runs r
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(lookback_days)s)
            group by r.strategy_code
            order by r.strategy_code asc
            """,
            {"lookback_days": lookback_days},
        )
        decoded = [self._calc_perf_row(row) for row in rows]
        filtered = [row for row in decoded if int(row.get('closed_replays', 0) or 0) >= min_closed]
        filtered.sort(key=lambda x: (x.get(metric) is not None, x.get(metric, float('-inf'))), reverse=True)
        ranked = []
        for idx, row in enumerate(filtered[:limit], start=1):
            ranked.append({"rank": idx, **row})
        return {
            "lookback_days": lookback_days,
            "metric": metric,
            "min_closed": min_closed,
            "limit": limit,
            "items": ranked,
        }

    def get_control_recommendations(self, *, short_window_days: int = 7, baseline_window_days: int = 30, lookback_days: int = 30) -> dict[str, Any]:
        drift = self.get_strategy_drift(short_window_days=short_window_days, baseline_window_days=baseline_window_days)
        scorecard = self.get_quality_scorecard(lookback_days=lookback_days)
        leaderboard = self.get_strategy_leaderboard(lookback_days=lookback_days, limit=50, min_closed=1, metric='avg_realized_pnl_pct')
        board_map = {item['strategy_code']: item for item in leaderboard['items']}
        recommendations = []
        for item in drift['items']:
            strategy_code = item['strategy_code']
            recent = item.get('recent', {})
            delta = item.get('delta', {})
            diagnosis = item.get('diagnosis')
            leaderboard_item = board_map.get(strategy_code, {})
            closed = int(recent.get('closed_replays', 0) or 0)
            avg_pnl = recent.get('avg_realized_pnl_pct')
            action = 'keep'
            reason = '성과가 대체로 안정적입니다.'
            if diagnosis == 'degrading' and closed >= 3:
                action = 'tighten_gate'
                reason = '최근 성과가 기준 구간 대비 악화되어 진입 게이트 강화가 필요합니다.'
                if (delta.get('win_rate_pct') is not None and delta['win_rate_pct'] <= -25.0) or (avg_pnl is not None and avg_pnl <= -2.5):
                    action = 'soft_disable'
                    reason = '최근 손익과 승률 저하 폭이 커서 일시 비활성화 권고입니다.'
            elif diagnosis == 'improving' and closed >= 3:
                action = 'expand'
                reason = '최근 성과 개선이 뚜렷하여 적용 비중 확대 검토가 가능합니다.'
            recommendations.append({
                'strategy_code': strategy_code,
                'action': action,
                'reason': reason,
                'diagnosis': diagnosis,
                'recent': recent,
                'delta': delta,
                'leaderboard': leaderboard_item,
            })
        action_counts: dict[str, int] = {}
        for rec in recommendations:
            action_counts[rec['action']] = action_counts.get(rec['action'], 0) + 1
        return {
            'scorecard': scorecard,
            'drift': drift,
            'leaderboard_metric': leaderboard['metric'],
            'recommendations': recommendations,
            'action_counts': action_counts,
        }

    def get_quality_scorecard(self, *, lookback_days: int = 30) -> dict[str, Any]:
        row = self.executor.fetch_one(
            """
            select
                count(*) as total_runs,
                count(*) filter (where se.display_text is not null and se.display_text <> '') as explanation_coverage_count,
                count(*) filter (where tp.strategy is not null and tp.strategy <> '') as trade_plan_coverage_count,
                count(*) filter (where rp.run_id is not null) as replay_coverage_count,
                count(*) filter (where rp.status = 'closed') as replay_closed_count,
                count(*) filter (where r.review_triggered = true) as review_triggered_count,
                count(*) filter (where coalesce(r.confidence, 0) < 0.55) as low_confidence_count,
                avg(r.confidence) as avg_confidence
            from ai_analysis_runs r
            left join ai_signal_explanations se on se.run_id = r.run_id
            left join ai_trade_plans tp on tp.run_id = r.run_id
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(lookback_days)s)
            """,
            {"lookback_days": lookback_days},
        ) or {}
        total = int(row.get('total_runs', 0) or 0)
        def pct(count_key: str) -> float | None:
            count = int(row.get(count_key, 0) or 0)
            return (count / total * 100.0) if total > 0 else None
        return {
            "lookback_days": lookback_days,
            "summary": self._decode_row(row),
            "rates": {
                "explanation_coverage_pct": pct('explanation_coverage_count'),
                "trade_plan_coverage_pct": pct('trade_plan_coverage_count'),
                "replay_coverage_pct": pct('replay_coverage_count'),
                "replay_closed_rate_pct": pct('replay_closed_count'),
                "review_trigger_rate_pct": pct('review_triggered_count'),
                "low_confidence_rate_pct": pct('low_confidence_count'),
            },
        }

    def get_strategy_drift(self, *, short_window_days: int = 7, baseline_window_days: int = 30) -> dict[str, Any]:
        recent_rows = self.executor.fetch_all(
            """
            select
                r.strategy_code,
                count(*) as runs,
                count(*) filter (where rp.status = 'closed') as closed_replays,
                count(*) filter (where rp.status = 'closed' and coalesce(rp.realized_pnl_pct, 0) > 0) as wins,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct
            from ai_analysis_runs r
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(short_window_days)s)
            group by r.strategy_code
            """,
            {"short_window_days": short_window_days},
        )
        baseline_rows = self.executor.fetch_all(
            """
            select
                r.strategy_code,
                count(*) as runs,
                count(*) filter (where rp.status = 'closed') as closed_replays,
                count(*) filter (where rp.status = 'closed' and coalesce(rp.realized_pnl_pct, 0) > 0) as wins,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct
            from ai_analysis_runs r
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(baseline_window_days)s)
              and r.created_at < now() - make_interval(days => %(short_window_days)s)
            group by r.strategy_code
            """,
            {"baseline_window_days": baseline_window_days, "short_window_days": short_window_days},
        )
        recent_map = {row['strategy_code']: self._calc_perf_row(row) for row in recent_rows}
        baseline_map = {row['strategy_code']: self._calc_perf_row(row) for row in baseline_rows}
        all_keys = sorted(set(recent_map) | set(baseline_map))
        items: list[dict[str, Any]] = []
        degraded: list[dict[str, Any]] = []
        improving: list[dict[str, Any]] = []
        stable: list[dict[str, Any]] = []
        for key in all_keys:
            recent = recent_map.get(key, {"strategy_code": key})
            baseline = baseline_map.get(key, {"strategy_code": key})
            win_rate_delta = self._delta(recent.get('win_rate_pct'), baseline.get('win_rate_pct'))
            pnl_delta = self._delta(recent.get('avg_realized_pnl_pct'), baseline.get('avg_realized_pnl_pct'))
            item = {
                "strategy_code": key,
                "recent": recent,
                "baseline": baseline,
                "delta": {
                    "win_rate_pct": win_rate_delta,
                    "avg_realized_pnl_pct": pnl_delta,
                },
                "diagnosis": self._drift_diagnosis(win_rate_delta, pnl_delta),
            }
            items.append(item)
            diag = item['diagnosis']
            if diag == 'degrading':
                degraded.append(item)
            elif diag == 'improving':
                improving.append(item)
            else:
                stable.append(item)
        return {
            "short_window_days": short_window_days,
            "baseline_window_days": baseline_window_days,
            "items": items,
            "degrading": degraded,
            "improving": improving,
            "stable": stable,
        }

    def list_runs(self, *, limit: int = 20, offset: int = 0, ticker: str | None = None, strategy_code: str | None = None, status: str | None = None) -> dict[str, Any]:
        where_parts = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if ticker:
            where_parts.append("e.ticker = %(ticker)s")
            params["ticker"] = ticker.upper()
        if strategy_code:
            where_parts.append("r.strategy_code = %(strategy_code)s")
            params["strategy_code"] = strategy_code
        if status:
            where_parts.append("r.status = %(status)s")
            params["status"] = status
        where_sql = " and ".join(where_parts)

        count_row = self.executor.fetch_one(
            f"""
            select count(*) as total
            from ai_analysis_runs r
            join ai_events e on e.event_id = r.event_id
            where {where_sql}
            """,
            params,
        ) or {"total": 0}

        rows = self.executor.fetch_all(
            f"""
            select r.run_id, r.event_id, e.ticker, e.company_name, e.event_time,
                   r.direction, r.magnitude, r.confidence, r.catalyst_type,
                   r.strategy_code, r.hold_days, r.review_triggered, r.status, r.created_at
            from ai_analysis_runs r
            join ai_events e on e.event_id = r.event_id
            where {where_sql}
            order by r.created_at desc
            limit %(limit)s offset %(offset)s
            """,
            params,
        )
        return {
            "items": [self._decode_row(row) for row in rows],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
                "total": int(count_row.get("total", 0) or 0),
            },
            "filters": {
                "ticker": ticker,
                "strategy_code": strategy_code,
                "status": status,
            },
        }

    def get_metrics_overview(self, *, lookback_days: int = 30) -> dict[str, Any]:
        summary = self.executor.fetch_one(
            """
            select
                count(*) as total_runs,
                count(*) filter (where r.status = 'ok') as ok_runs,
                count(*) filter (where rp.status = 'closed') as closed_replays,
                count(*) filter (where rp.status = 'closed' and coalesce(rp.realized_pnl_pct, 0) > 0) as winning_replays,
                avg(r.confidence) as avg_confidence,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct,
                avg(rp.mfe_pct) filter (where rp.status = 'closed') as avg_mfe_pct,
                avg(rp.mae_pct) filter (where rp.status = 'closed') as avg_mae_pct
            from ai_analysis_runs r
            join ai_events e on e.event_id = r.event_id
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(lookback_days)s)
            """,
            {"lookback_days": lookback_days},
        ) or {}

        strategy_rows = self.executor.fetch_all(
            """
            select
                r.strategy_code,
                count(*) as runs,
                count(*) filter (where rp.status = 'closed') as closed_replays,
                count(*) filter (where rp.status = 'closed' and coalesce(rp.realized_pnl_pct, 0) > 0) as wins,
                avg(r.confidence) as avg_confidence,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct
            from ai_analysis_runs r
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(lookback_days)s)
            group by r.strategy_code
            order by runs desc, r.strategy_code asc
            """,
            {"lookback_days": lookback_days},
        )

        ticker_rows = self.executor.fetch_all(
            """
            select
                e.ticker,
                count(*) as runs,
                avg(r.confidence) as avg_confidence,
                avg(rp.realized_pnl_pct) filter (where rp.status = 'closed') as avg_realized_pnl_pct
            from ai_analysis_runs r
            join ai_events e on e.event_id = r.event_id
            left join ai_replay_tracks rp on rp.run_id = r.run_id
            where r.created_at >= now() - make_interval(days => %(lookback_days)s)
            group by e.ticker
            order by runs desc, e.ticker asc
            limit 10
            """,
            {"lookback_days": lookback_days},
        )

        total_closed = int(summary.get("closed_replays", 0) or 0)
        wins = int(summary.get("winning_replays", 0) or 0)
        win_rate = (wins / total_closed * 100.0) if total_closed > 0 else None

        return {
            "lookback_days": lookback_days,
            "summary": {
                **self._decode_row(summary),
                "win_rate_pct": win_rate,
            },
            "by_strategy": [self._with_win_rate(row) for row in strategy_rows],
            "top_tickers": [self._decode_row(row) for row in ticker_rows],
        }

    def update_replay_track(self, run_id: str, patch: Mapping[str, Any]) -> ReplayUpdateResult:
        fields = dict(patch)
        if not fields:
            return ReplayUpdateResult(updated=False, run_id=run_id, fields_updated=[])

        supported_fields = {
            "status",
            "original_signal",
            "milestones",
            "expected_path",
            "exit_watch",
            "realized_pnl_pct",
            "mfe_pct",
            "mae_pct",
            "close_reason",
        }
        invalid = [field for field in fields if field not in supported_fields]
        if invalid:
            raise ValueError(f"Unsupported replay patch fields: {', '.join(sorted(invalid))}")

        set_parts: list[str] = []
        params: dict[str, Any] = {"run_id": run_id}

        for field, value in fields.items():
            column = {
                "original_signal": "original_signal_json",
                "milestones": "milestones_json",
            }.get(field, field)
            if field in {"original_signal", "milestones"}:
                params[field] = self._json(value)
                set_parts.append(f"{column} = %({field})s::jsonb")
            else:
                params[field] = value
                set_parts.append(f"{column} = %({field})s")

        set_parts.append("updated_at = now()")
        query = f"""
        update ai_replay_tracks
        set {', '.join(set_parts)}
        where run_id = %(run_id)s
        """
        self.executor.execute(query, params)
        return ReplayUpdateResult(updated=True, run_id=run_id, fields_updated=sorted(fields.keys()))

    def _build_statements(self, envelope: Mapping[str, Any]) -> tuple[list[tuple[str, dict[str, Any]]], str, str, dict[str, int]]:
        data = self._require_dict(envelope, "data")
        event = self._require_dict(data, "event")
        analysis_view = self._require_dict(data, "analysis")
        market_snapshot = self._require_dict(data, "market_snapshot")
        paywall = self._optional_dict(data.get("paywall"))
        replay = self._optional_dict(data.get("replay"))
        cards = data.get("cards") if isinstance(data.get("cards"), list) else []
        legacy_analysis = self._optional_dict(envelope.get("analysis"))
        metadata = self._optional_dict(envelope.get("metadata"))
        signal_explanation = self._optional_dict(analysis_view.get("signal_explanation"))
        signal_brief = self._optional_dict(data.get("signal_brief")) or self._optional_dict(envelope.get("signal_brief"))
        strategy_decision = self._optional_dict(analysis_view.get("strategy_decision"))
        topic_deltas = self._optional_dict(analysis_view.get("topic_deltas"))
        feature_bundle = self._optional_dict(analysis_view.get("feature_bundle")) or self._optional_dict(metadata.get("feature_bundle"))
        trade_plan = self._extract_trade_plan(metadata=metadata, cards=cards)

        event_id = str(event["event_id"])
        request_id = str(envelope.get("request_id") or f"req_{event_id}")
        run_id = self._build_run_id(event_id=event_id, request_id=request_id)

        statements: list[tuple[str, dict[str, Any]]] = []
        row_counts = {
            "ai_events": 1,
            "ai_analysis_runs": 1,
            "ai_feature_snapshots": 1,
            "ai_signal_explanations": 1,
            "ai_trade_plans": 1,
            "ai_cards": len(cards),
            "ai_paywall_surfaces": 1,
            "ai_replay_tracks": 1,
        }

        statements.append((
            """
            insert into ai_events (
                event_id, ticker, company_name, source_type, event_type, event_time,
                market_session, sector, external_source_id, chunk_sequence, is_final_chunk,
                schema_version, created_at, updated_at
            ) values (
                %(event_id)s, %(ticker)s, %(company_name)s, %(source_type)s, %(event_type)s, %(event_time)s,
                %(market_session)s, %(sector)s, %(external_source_id)s, %(chunk_sequence)s, %(is_final_chunk)s,
                %(schema_version)s, now(), now()
            )
            on conflict (event_id) do update set
                company_name = excluded.company_name,
                market_session = excluded.market_session,
                sector = excluded.sector,
                schema_version = excluded.schema_version,
                updated_at = now()
            """,
            {
                "event_id": event_id,
                "ticker": event.get("ticker"),
                "company_name": event.get("company_name") or event.get("ticker"),
                "source_type": event.get("event_type") or "unknown",
                "event_type": event.get("event_type") or "unknown",
                "event_time": event.get("event_time"),
                "market_session": event.get("market_session") or "unknown",
                "sector": event.get("sector"),
                "external_source_id": None,
                "chunk_sequence": self._safe_int(self._extract_chunk_sequence(request_id=request_id, event_id=event_id)),
                "is_final_chunk": False,
                "schema_version": event.get("schema_version") or envelope.get("schema_version"),
            },
        ))

        statements.append((
            """
            insert into ai_analysis_runs (
                run_id, event_id, request_id, route_profile, model_route, model_version, app_version,
                direction, magnitude, confidence, catalyst_type, rationale, strategy_code,
                strategy_score, hold_days, review_triggered, status, raw_analysis_json, created_at
            ) values (
                %(run_id)s, %(event_id)s, %(request_id)s, %(route_profile)s, %(model_route)s, %(model_version)s, %(app_version)s,
                %(direction)s, %(magnitude)s, %(confidence)s, %(catalyst_type)s, %(rationale)s, %(strategy_code)s,
                %(strategy_score)s, %(hold_days)s, %(review_triggered)s, %(status)s, %(raw_analysis_json)s::jsonb, now()
            )
            on conflict (run_id) do update set
                direction = excluded.direction,
                magnitude = excluded.magnitude,
                confidence = excluded.confidence,
                catalyst_type = excluded.catalyst_type,
                rationale = excluded.rationale,
                strategy_code = excluded.strategy_code,
                strategy_score = excluded.strategy_score,
                hold_days = excluded.hold_days,
                review_triggered = excluded.review_triggered,
                status = excluded.status,
                raw_analysis_json = excluded.raw_analysis_json
            """,
            {
                "run_id": run_id,
                "event_id": event_id,
                "request_id": request_id,
                "route_profile": self._infer_route_profile(envelope=envelope, legacy_analysis=legacy_analysis),
                "model_route": legacy_analysis.get("model_version") or envelope.get("model_version"),
                "model_version": legacy_analysis.get("model_version") or envelope.get("model_version"),
                "app_version": envelope.get("schema_version"),
                "direction": analysis_view.get("direction"),
                "magnitude": self._safe_float(analysis_view.get("magnitude")),
                "confidence": self._safe_float(analysis_view.get("confidence")),
                "catalyst_type": analysis_view.get("catalyst_type"),
                "rationale": strategy_decision.get("rationale") or legacy_analysis.get("rationale"),
                "strategy_code": strategy_decision.get("strategy") or envelope.get("strategy"),
                "strategy_score": self._safe_float(strategy_decision.get("score")),
                "hold_days": self._safe_int(strategy_decision.get("hold_days")) or 1,
                "review_triggered": bool(legacy_analysis.get("review_triggered")),
                "status": envelope.get("status") or "ok",
                "raw_analysis_json": self._json(legacy_analysis),
            },
        ))

        statements.append((
            """
            insert into ai_feature_snapshots (
                run_id, market_snapshot_json, topic_deltas_json, transcript_signals_json,
                phase1_json, router_json, canonical_bundle_json, source_health_json, created_at
            ) values (
                %(run_id)s, %(market_snapshot_json)s::jsonb, %(topic_deltas_json)s::jsonb, %(transcript_signals_json)s::jsonb,
                %(phase1_json)s::jsonb, %(router_json)s::jsonb, %(canonical_bundle_json)s::jsonb, %(source_health_json)s::jsonb, now()
            )
            on conflict (run_id) do update set
                market_snapshot_json = excluded.market_snapshot_json,
                topic_deltas_json = excluded.topic_deltas_json,
                transcript_signals_json = excluded.transcript_signals_json,
                phase1_json = excluded.phase1_json,
                router_json = excluded.router_json,
                canonical_bundle_json = excluded.canonical_bundle_json,
                source_health_json = excluded.source_health_json
            """,
            {
                "run_id": run_id,
                "market_snapshot_json": self._json(market_snapshot),
                "topic_deltas_json": self._json(topic_deltas),
                "transcript_signals_json": self._json(metadata.get("transcript_signals") or {}),
                "phase1_json": self._json(metadata.get("phase1") or {}),
                "router_json": self._json(metadata.get("router") or {}),
                "canonical_bundle_json": self._json(metadata.get("canonical_bundle") or feature_bundle),
                "source_health_json": self._json(metadata.get("source_health_summary") or metadata.get("source_health") or {}),
            },
        ))

        statements.append((
            """
            insert into ai_signal_explanations (
                run_id, display_text, summary_ko, reasons_json, risks_json,
                counter_scenario, hold_period_reason, details_json, signal_brief_json, created_at
            ) values (
                %(run_id)s, %(display_text)s, %(summary_ko)s, %(reasons_json)s::jsonb, %(risks_json)s::jsonb,
                %(counter_scenario)s, %(hold_period_reason)s, %(details_json)s::jsonb, %(signal_brief_json)s::jsonb, now()
            )
            on conflict (run_id) do update set
                display_text = excluded.display_text,
                summary_ko = excluded.summary_ko,
                reasons_json = excluded.reasons_json,
                risks_json = excluded.risks_json,
                counter_scenario = excluded.counter_scenario,
                hold_period_reason = excluded.hold_period_reason,
                details_json = excluded.details_json,
                signal_brief_json = excluded.signal_brief_json
            """,
            {
                "run_id": run_id,
                "display_text": signal_explanation.get("display_text"),
                "summary_ko": signal_explanation.get("summary_ko"),
                "reasons_json": self._json(signal_explanation.get("reasons") or []),
                "risks_json": self._json(signal_explanation.get("risks") or []),
                "counter_scenario": signal_explanation.get("counter_scenario"),
                "hold_period_reason": signal_explanation.get("hold_period_reason"),
                "details_json": self._json(signal_explanation),
                "signal_brief_json": self._json(signal_brief),
            },
        ))

        statements.append((
            """
            insert into ai_trade_plans (
                run_id, strategy, strategy_label_ko, entry_style, entry_style_label_ko,
                entry_zone, stop_loss, take_profit_1, take_profit_2, invalidation,
                time_stop, positioning_note, raw_trade_plan_json, created_at
            ) values (
                %(run_id)s, %(strategy)s, %(strategy_label_ko)s, %(entry_style)s, %(entry_style_label_ko)s,
                %(entry_zone)s, %(stop_loss)s, %(take_profit_1)s, %(take_profit_2)s, %(invalidation)s,
                %(time_stop)s, %(positioning_note)s, %(raw_trade_plan_json)s::jsonb, now()
            )
            on conflict (run_id) do update set
                strategy = excluded.strategy,
                strategy_label_ko = excluded.strategy_label_ko,
                entry_style = excluded.entry_style,
                entry_style_label_ko = excluded.entry_style_label_ko,
                entry_zone = excluded.entry_zone,
                stop_loss = excluded.stop_loss,
                take_profit_1 = excluded.take_profit_1,
                take_profit_2 = excluded.take_profit_2,
                invalidation = excluded.invalidation,
                time_stop = excluded.time_stop,
                positioning_note = excluded.positioning_note,
                raw_trade_plan_json = excluded.raw_trade_plan_json
            """,
            {
                "run_id": run_id,
                "strategy": trade_plan.get("strategy") or strategy_decision.get("strategy") or envelope.get("strategy"),
                "strategy_label_ko": trade_plan.get("strategy_label_ko") or trade_plan.get("strategy") or strategy_decision.get("strategy"),
                "entry_style": trade_plan.get("entry_style"),
                "entry_style_label_ko": trade_plan.get("entry_style_label_ko"),
                "entry_zone": trade_plan.get("entry_zone"),
                "stop_loss": self._safe_float(trade_plan.get("stop_loss")),
                "take_profit_1": self._safe_float(trade_plan.get("take_profit_1")),
                "take_profit_2": self._safe_float(trade_plan.get("take_profit_2")),
                "invalidation": trade_plan.get("invalidation"),
                "time_stop": trade_plan.get("time_stop"),
                "positioning_note": trade_plan.get("positioning_note"),
                "raw_trade_plan_json": self._json(trade_plan),
            },
        ))

        for card in cards:
            payload = self._optional_dict(card.get("payload")) or card.get("payload") or {}
            lock_context = self._optional_dict(card.get("lock_context"))
            statements.append((
                """
                insert into ai_cards (
                    card_id, run_id, event_id, card_type, priority, visible,
                    locked, payload_json, lock_context_json, created_at
                ) values (
                    %(card_id)s, %(run_id)s, %(event_id)s, %(card_type)s, %(priority)s, %(visible)s,
                    %(locked)s, %(payload_json)s::jsonb, %(lock_context_json)s::jsonb, now()
                )
                on conflict (card_id) do update set
                    priority = excluded.priority,
                    visible = excluded.visible,
                    locked = excluded.locked,
                    payload_json = excluded.payload_json,
                    lock_context_json = excluded.lock_context_json
                """,
                {
                    "card_id": card.get("card_id"),
                    "run_id": run_id,
                    "event_id": event_id,
                    "card_type": card.get("card_type"),
                    "priority": self._safe_int(card.get("priority")) or 999,
                    "visible": bool(card.get("visible", True)),
                    "locked": bool(card.get("locked", False)),
                    "payload_json": self._json(payload),
                    "lock_context_json": self._json(lock_context or {}),
                },
            ))

        statements.append((
            """
            insert into ai_paywall_surfaces (
                run_id, primary_surface_code, primary_surface_json, secondary_surfaces_json,
                unlock_cards_json, frontend_contract_json, summary, created_at
            ) values (
                %(run_id)s, %(primary_surface_code)s, %(primary_surface_json)s::jsonb, %(secondary_surfaces_json)s::jsonb,
                %(unlock_cards_json)s::jsonb, %(frontend_contract_json)s::jsonb, %(summary)s, now()
            )
            on conflict (run_id) do update set
                primary_surface_code = excluded.primary_surface_code,
                primary_surface_json = excluded.primary_surface_json,
                secondary_surfaces_json = excluded.secondary_surfaces_json,
                unlock_cards_json = excluded.unlock_cards_json,
                frontend_contract_json = excluded.frontend_contract_json,
                summary = excluded.summary
            """,
            {
                "run_id": run_id,
                "primary_surface_code": self._optional_dict(paywall.get("primary_surface")).get("code") if isinstance(paywall.get("primary_surface"), dict) else None,
                "primary_surface_json": self._json(paywall.get("primary_surface") or {}),
                "secondary_surfaces_json": self._json(paywall.get("secondary_surfaces") or []),
                "unlock_cards_json": self._json(paywall.get("unlock_cards") or []),
                "frontend_contract_json": self._json(paywall.get("frontend_contract_ko") or {}),
                "summary": paywall.get("summary"),
            },
        ))

        statements.append((
            """
            insert into ai_replay_tracks (
                run_id, event_id, status, original_signal_json, milestones_json,
                expected_path, exit_watch, realized_pnl_pct, mfe_pct, mae_pct,
                close_reason, created_at, updated_at
            ) values (
                %(run_id)s, %(event_id)s, %(status)s, %(original_signal_json)s::jsonb, %(milestones_json)s::jsonb,
                %(expected_path)s, %(exit_watch)s, %(realized_pnl_pct)s, %(mfe_pct)s, %(mae_pct)s,
                %(close_reason)s, now(), now()
            )
            on conflict (run_id) do update set
                status = excluded.status,
                original_signal_json = excluded.original_signal_json,
                milestones_json = excluded.milestones_json,
                expected_path = excluded.expected_path,
                exit_watch = excluded.exit_watch,
                realized_pnl_pct = excluded.realized_pnl_pct,
                mfe_pct = excluded.mfe_pct,
                mae_pct = excluded.mae_pct,
                close_reason = excluded.close_reason,
                updated_at = now()
            """,
            {
                "run_id": run_id,
                "event_id": event_id,
                "status": replay.get("status") or "tracking",
                "original_signal_json": self._json(replay.get("original_signal") or {}),
                "milestones_json": self._json(replay.get("milestones") or []),
                "expected_path": replay.get("expected_path"),
                "exit_watch": replay.get("exit_watch"),
                "realized_pnl_pct": self._safe_float(replay.get("realized_pnl_pct")),
                "mfe_pct": self._safe_float(replay.get("mfe_pct")),
                "mae_pct": self._safe_float(replay.get("mae_pct")),
                "close_reason": replay.get("close_reason"),
            },
        ))

        return statements, event_id, run_id, row_counts

    @staticmethod
    def _extract_trade_plan(*, metadata: Mapping[str, Any], cards: list[Any]) -> dict[str, Any]:
        trade_plan = metadata.get("trade_plan") if isinstance(metadata.get("trade_plan"), dict) else None
        if isinstance(trade_plan, dict):
            return dict(trade_plan)
        for card in cards:
            if isinstance(card, dict) and card.get("card_type") == "trade_plan":
                payload = card.get("payload") if isinstance(card.get("payload"), dict) else {}
                return dict(payload)
        return {}

    @staticmethod
    def _require_dict(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
        value = mapping.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"Missing or invalid '{key}' object in engine envelope")
        return value

    @staticmethod
    def _optional_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)

    @staticmethod
    def _maybe_json(value: Any) -> Any:
        if isinstance(value, str) and value and value[0] in '[{':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @classmethod
    def _decode_row(cls, row: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: cls._maybe_json(value) for key, value in dict(row).items()}

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _delta(a: Any, b: Any) -> float | None:
        if a is None or b is None:
            return None
        try:
            return float(a) - float(b)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _calc_perf_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        decoded = cls._decode_row(row) or {}
        closed = int(decoded.get("closed_replays", 0) or 0)
        wins = int(decoded.get("wins", 0) or 0)
        decoded["win_rate_pct"] = (wins / closed * 100.0) if closed > 0 else None
        return decoded

    @staticmethod
    def _drift_diagnosis(win_rate_delta: float | None, pnl_delta: float | None) -> str:
        if (win_rate_delta is not None and win_rate_delta <= -15.0) or (pnl_delta is not None and pnl_delta <= -2.0):
            return 'degrading'
        if (win_rate_delta is not None and win_rate_delta >= 15.0) or (pnl_delta is not None and pnl_delta >= 2.0):
            return 'improving'
        return 'stable'

    @classmethod
    def _with_win_rate(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        decoded = cls._decode_row(row)
        if decoded is None:
            return {}
        closed = int(decoded.get("closed_replays", 0) or 0)
        wins = int(decoded.get("wins", 0) or 0)
        decoded["win_rate_pct"] = (wins / closed * 100.0) if closed > 0 else None
        return decoded

    @staticmethod
    def _build_run_id(*, event_id: str, request_id: str) -> str:
        digest = hashlib.sha1(f"{event_id}:{request_id}".encode("utf-8")).hexdigest()[:20]
        return f"run_{digest}"

    @staticmethod
    def _extract_chunk_sequence(*, request_id: str, event_id: str) -> int:
        for source in (request_id, event_id):
            tail = str(source).split("_")[-1]
            if tail.isdigit():
                return int(tail)
        return 1

    @staticmethod
    def _infer_route_profile(*, envelope: Mapping[str, Any], legacy_analysis: Mapping[str, Any]) -> str:
        if legacy_analysis.get("review_triggered"):
            return "review"
        request_id = str(envelope.get("request_id") or "")
        return "review" if "review" in request_id else "economy"



def _save_gate_patch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    self.executor.execute(
        """
        insert into ai_strategy_gate_patches (strategy_code, patch_json, rationale_ko, source, applied, created_by)
        values (%(strategy_code)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(source)s, %(applied)s, %(created_by)s)
        """,
        {
            'strategy_code': payload['strategy_code'],
            'patch_json': self._json(payload.get('patch') or {}),
            'rationale_ko': payload.get('rationale_ko'),
            'source': payload.get('source'),
            'applied': payload.get('applied', False),
            'created_by': payload.get('created_by'),
        },
    )
    return {
        'patch_id': 1,
        'strategy_code': payload['strategy_code'],
        'patch_json': payload.get('patch') or {},
        'rationale_ko': payload.get('rationale_ko'),
        'source': payload.get('source'),
        'applied': payload.get('applied', False),
        'created_by': payload.get('created_by'),
    }


def _list_gate_patches(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {'limit': limit, 'offset': offset}
    if strategy_code:
        where.append('strategy_code = %(strategy_code)s')
        params['strategy_code'] = strategy_code
    where_sql = ('where ' + ' and '.join(where)) if where else ''
    rows = self.executor.fetch_all(
        f"""
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at
        from ai_strategy_gate_patches
        {where_sql}
        order by patch_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {'items': [self._decode_row(r) for r in rows], 'limit': limit, 'offset': offset, 'strategy_code': strategy_code}


def _save_alert_state_action(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    self.executor.execute(
        """
        insert into ai_alert_state_actions (code, scope, status, note, muted_until, actor)
        values (%(code)s, %(scope)s, %(status)s, %(note)s, %(muted_until)s, %(actor)s)
        """,
        payload,
    )
    return {'action_id': 1, 'code': payload['code'], 'scope': payload.get('scope', 'global'), 'status': payload['status'], 'note': payload.get('note'), 'muted_until': payload.get('muted_until'), 'actor': payload.get('actor')}


def _list_alert_state_actions(self, *, code: str | None = None, scope: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {'limit': limit, 'offset': offset}
    if code:
        where.append('code = %(code)s')
        params['code'] = code
    if scope:
        where.append('scope = %(scope)s')
        params['scope'] = scope
    where_sql = ('where ' + ' and '.join(where)) if where else ''
    rows = self.executor.fetch_all(
        f"""
        select action_id, code, scope, status, note, muted_until, actor, created_at
        from ai_alert_state_actions
        {where_sql}
        order by action_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {'items': [self._decode_row(r) for r in rows], 'limit': limit, 'offset': offset, 'code': code, 'scope': scope}


def _apply_gate_patch(self, patch_id: int, *, actor: str | None = None) -> dict[str, Any]:
    patch = self.executor.fetch_one(
        """
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at
        from ai_strategy_gate_patches
        where patch_id = %(patch_id)s
        """,
        {'patch_id': patch_id},
    )
    decoded = self._decode_row(patch)
    if not decoded:
        raise ValueError('patch_id not found')
    self.executor.execute(
        """
        insert into ai_strategy_gate_active_configs (strategy_code, active_patch_id, patch_json, rationale_ko, updated_by)
        values (%(strategy_code)s, %(patch_id)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(updated_by)s)
        on conflict (strategy_code) do update set
            active_patch_id = excluded.active_patch_id,
            patch_json = excluded.patch_json,
            rationale_ko = excluded.rationale_ko,
            updated_by = excluded.updated_by,
            updated_at = now()
        """,
        {
            'strategy_code': decoded['strategy_code'],
            'patch_id': decoded['patch_id'],
            'patch_json': self._json(decoded.get('patch_json') or {}),
            'rationale_ko': decoded.get('rationale_ko'),
            'updated_by': actor,
        },
    )
    self.executor.execute("update ai_strategy_gate_patches set applied = true where patch_id = %(patch_id)s", {'patch_id': patch_id})
    return {'strategy_code': decoded['strategy_code'], 'active_patch_id': decoded['patch_id'], 'patch_json': decoded.get('patch_json') or {}, 'rationale_ko': decoded.get('rationale_ko'), 'updated_by': actor, 'applied': True}


def _list_active_gate_configs(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {'limit': limit, 'offset': offset}
    if strategy_code:
        where.append('strategy_code = %(strategy_code)s')
        params['strategy_code'] = strategy_code
    where_sql = ('where ' + ' and '.join(where)) if where else ''
    rows = self.executor.fetch_all(
        f"""
        select strategy_code, active_patch_id, patch_json, rationale_ko, updated_by, updated_at
        from ai_strategy_gate_active_configs
        {where_sql}
        order by updated_at desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {'items': [self._decode_row(r) for r in rows], 'limit': limit, 'offset': offset, 'strategy_code': strategy_code}


def _rollback_active_gate_config(self, strategy_code: str, *, target_patch_id: int, actor: str | None = None) -> dict[str, Any]:
    patch = self.executor.fetch_one(
        """
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at
        from ai_strategy_gate_patches
        where patch_id = %(patch_id)s and strategy_code = %(strategy_code)s
        """,
        {'patch_id': target_patch_id, 'strategy_code': strategy_code},
    )
    decoded = self._decode_row(patch)
    if not decoded:
        raise ValueError('target_patch_id not found for strategy_code')
    self.executor.execute(
        """
        insert into ai_strategy_gate_active_configs (strategy_code, active_patch_id, patch_json, rationale_ko, updated_by)
        values (%(strategy_code)s, %(patch_id)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(updated_by)s)
        on conflict (strategy_code) do update set
            active_patch_id = excluded.active_patch_id,
            patch_json = excluded.patch_json,
            rationale_ko = excluded.rationale_ko,
            updated_by = excluded.updated_by,
            updated_at = now()
        """,
        {
            'strategy_code': strategy_code,
            'patch_id': decoded['patch_id'],
            'patch_json': self._json(decoded.get('patch_json') or {}),
            'rationale_ko': decoded.get('rationale_ko'),
            'updated_by': actor,
        },
    )
    return {'strategy_code': strategy_code, 'active_patch_id': decoded['patch_id'], 'patch_json': decoded.get('patch_json') or {}, 'rationale_ko': decoded.get('rationale_ko'), 'updated_by': actor, 'action': 'rollback_to_patch'}


EventStoreRepository.save_gate_patch = _save_gate_patch
EventStoreRepository.list_gate_patches = _list_gate_patches
EventStoreRepository.save_alert_state_action = _save_alert_state_action
EventStoreRepository.list_alert_state_actions = _list_alert_state_actions
EventStoreRepository.apply_gate_patch = _apply_gate_patch
EventStoreRepository.list_active_gate_configs = _list_active_gate_configs
EventStoreRepository.rollback_active_gate_config = _rollback_active_gate_config


def _normalize_market_cap_bucket(self, market_cap: Any) -> str:
    value = self._safe_float(market_cap)
    if value is None:
        return "unknown"
    if value >= 200_000_000_000:
        return "mega"
    if value >= 10_000_000_000:
        return "large"
    if value >= 2_000_000_000:
        return "mid"
    if value >= 300_000_000:
        return "small"
    return "micro"


def _materialize_thresholds(self, *, strategy_code: str, patch_json: Mapping[str, Any] | None = None) -> dict[str, float]:
    patch_json = dict(patch_json or {})
    defaults = {
        "min_confidence": 0.55,
        "min_composite": 0.45,
        "min_raw_score": 0.35,
        "min_volume_ratio": 1.0,
        "min_event_quality": 0.35,
        "max_gap_overshoot": 3.0,
        "position_scale_delta": 0.0,
        "max_hold_days_delta": 0.0,
    }
    defaults["min_confidence"] = max(0.0, min(1.0, defaults["min_confidence"] + float(patch_json.get("min_confidence_delta", 0.0) or 0.0)))
    defaults["min_composite"] = float(patch_json.get("min_composite", defaults["min_composite"]) or defaults["min_composite"])
    defaults["min_raw_score"] = float(patch_json.get("min_raw_score", defaults["min_raw_score"]) or defaults["min_raw_score"])
    defaults["min_volume_ratio"] = float(patch_json.get("min_volume_ratio", defaults["min_volume_ratio"]) or defaults["min_volume_ratio"])
    defaults["min_event_quality"] = float(patch_json.get("min_event_quality", defaults["min_event_quality"]) or defaults["min_event_quality"])
    defaults["max_gap_overshoot"] = float(patch_json.get("max_gap_overshoot", defaults["max_gap_overshoot"]) or defaults["max_gap_overshoot"])
    defaults["position_scale_delta"] = float(patch_json.get("position_scale_delta", defaults["position_scale_delta"]) or defaults["position_scale_delta"])
    defaults["max_hold_days_delta"] = float(patch_json.get("max_hold_days_delta", defaults["max_hold_days_delta"]) or defaults["max_hold_days_delta"])
    return defaults


def _extract_event_quality(self, analysis: Mapping[str, Any]) -> float:
    metadata = analysis.get("metadata")
    if not isinstance(metadata, Mapping):
        return 0.0
    event_quality = metadata.get("event_quality")
    if not isinstance(event_quality, Mapping):
        return 0.0
    strategy_code = str(analysis.get("strategy") or "").lower()
    strategy_quality = event_quality.get(strategy_code)
    if isinstance(strategy_quality, Mapping):
        return float(strategy_quality.get("total", 0.0) or 0.0)
    return 0.0


def _compute_gap_overshoot(self, market_data: Any) -> float:
    gap_pct = self._safe_float(getattr(market_data, "gap_pct", None))
    implied_move_pct = self._safe_float(getattr(market_data, "implied_move_pct", None))
    if gap_pct is None or implied_move_pct is None:
        return 0.0
    return max(0.0, abs(gap_pct) - abs(implied_move_pct))


def _fetch_inserted(self, query: str, params: Mapping[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    row = self.executor.fetch_one(query, params)
    decoded = self._decode_row(row)
    return decoded or fallback


def _save_patch_audit_log(
    self,
    *,
    patch_id: int,
    event_type: str,
    status_from: str | None,
    status_to: str | None,
    approval_state_from: str | None,
    approval_state_to: str | None,
    payload: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    fallback = {
        "audit_id": 1,
        "patch_id": patch_id,
        "event_type": event_type,
        "status_from": status_from,
        "status_to": status_to,
        "approval_state_from": approval_state_from,
        "approval_state_to": approval_state_to,
        "payload_json": payload or {},
        "actor": actor,
    }
    return self._fetch_inserted(
        """
        insert into ai_gate_patch_audit_logs (
            patch_id, event_type, status_from, status_to, approval_state_from, approval_state_to, payload_json, actor
        ) values (
            %(patch_id)s, %(event_type)s, %(status_from)s, %(status_to)s, %(approval_state_from)s, %(approval_state_to)s, %(payload_json)s::jsonb, %(actor)s
        )
        returning audit_id, patch_id, event_type, status_from, status_to, approval_state_from, approval_state_to, payload_json, actor, created_at
        """,
        {
            "patch_id": patch_id,
            "event_type": event_type,
            "status_from": status_from,
            "status_to": status_to,
            "approval_state_from": approval_state_from,
            "approval_state_to": approval_state_to,
            "payload_json": self._json(payload or {}),
            "actor": actor,
        },
        fallback,
    )


def _get_gate_patch(self, patch_id: int) -> dict[str, Any] | None:
    row = self.executor.fetch_one(
        """
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at,
               patch_type, scope_type, scope_key, regime, sector_code, market_cap_bucket, ticker, universe_profile,
               parent_patch_id, report_id, status, approval_state, last_transition_at
        from ai_strategy_gate_patches
        where patch_id = %(patch_id)s
        """,
        {"patch_id": patch_id},
    )
    return self._decode_row(row)


def _save_gate_patch_v2(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    fallback = {
        "patch_id": 1,
        "strategy_code": payload["strategy_code"],
        "patch_json": payload.get("patch") or {},
        "rationale_ko": payload.get("rationale_ko"),
        "source": payload.get("source"),
        "applied": payload.get("applied", False),
        "created_by": payload.get("created_by"),
        "patch_type": payload.get("patch_type", "manual"),
        "scope_type": payload.get("scope_type", "strategy_global"),
        "scope_key": payload.get("scope_key"),
        "regime": payload.get("regime"),
        "sector_code": payload.get("sector_code"),
        "market_cap_bucket": payload.get("market_cap_bucket"),
        "ticker": payload.get("ticker"),
        "universe_profile": payload.get("universe_profile"),
        "parent_patch_id": payload.get("parent_patch_id"),
        "report_id": payload.get("report_id"),
        "status": payload.get("status") or "draft",
        "approval_state": payload.get("approval_state") or "pending",
        "audit_trail_count": 0,
        "active_rollout_id": None,
    }
    saved = self._fetch_inserted(
        """
        insert into ai_strategy_gate_patches (
            strategy_code, patch_json, rationale_ko, source, applied, created_by, patch_type, scope_type, scope_key,
            regime, sector_code, market_cap_bucket, ticker, universe_profile, parent_patch_id, report_id, status, approval_state
        ) values (
            %(strategy_code)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(source)s, %(applied)s, %(created_by)s, %(patch_type)s, %(scope_type)s, %(scope_key)s,
            %(regime)s, %(sector_code)s, %(market_cap_bucket)s, %(ticker)s, %(universe_profile)s, %(parent_patch_id)s, %(report_id)s, %(status)s, %(approval_state)s
        )
        returning patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at,
                  patch_type, scope_type, scope_key, regime, sector_code, market_cap_bucket, ticker, universe_profile,
                  parent_patch_id, report_id, status, approval_state, last_transition_at
        """,
        {
            "strategy_code": payload["strategy_code"],
            "patch_json": self._json(payload.get("patch") or {}),
            "rationale_ko": payload.get("rationale_ko"),
            "source": payload.get("source"),
            "applied": payload.get("applied", False),
            "created_by": payload.get("created_by"),
            "patch_type": payload.get("patch_type", "manual"),
            "scope_type": payload.get("scope_type", "strategy_global"),
            "scope_key": payload.get("scope_key"),
            "regime": payload.get("regime"),
            "sector_code": payload.get("sector_code"),
            "market_cap_bucket": payload.get("market_cap_bucket"),
            "ticker": payload.get("ticker"),
            "universe_profile": payload.get("universe_profile"),
            "parent_patch_id": payload.get("parent_patch_id"),
            "report_id": payload.get("report_id"),
            "status": payload.get("status") or "draft",
            "approval_state": payload.get("approval_state") or "pending",
        },
        fallback,
    )
    self.save_patch_audit_log(
        patch_id=int(saved["patch_id"]),
        event_type="patch_created",
        status_from=None,
        status_to=str(saved.get("status") or "draft"),
        approval_state_from=None,
        approval_state_to=str(saved.get("approval_state") or "pending"),
        payload={"patch_json": saved.get("patch_json") or {}, "scope_type": saved.get("scope_type")},
        actor=saved.get("created_by"),
    )
    saved["audit_trail_count"] = 1
    saved["active_rollout_id"] = None
    return saved


def _list_gate_patches_v2(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0, status: str | None = None) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if strategy_code:
        where.append("strategy_code = %(strategy_code)s")
        params["strategy_code"] = strategy_code
    if status:
        where.append("status = %(status)s")
        params["status"] = status
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select p.patch_id, p.strategy_code, p.patch_json, p.rationale_ko, p.source, p.applied, p.created_by, p.created_at,
               p.patch_type, p.scope_type, p.scope_key, p.regime, p.sector_code, p.market_cap_bucket, p.ticker, p.universe_profile,
               p.parent_patch_id, p.report_id, p.status, p.approval_state, p.last_transition_at,
               (select count(*) from ai_gate_patch_audit_logs a where a.patch_id = p.patch_id) as audit_trail_count,
               (select max(r.rollout_id) from ai_gate_rollouts r where r.patch_id = p.patch_id and r.status like '%%active') as active_rollout_id
        from ai_strategy_gate_patches p
        {where_sql}
        order by p.patch_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "strategy_code": strategy_code, "status": status}


def _approve_gate_patch(self, patch_id: int, *, actor: str | None = None, note: str | None = None, approved_for_prod: bool = False, strict_prod_policy_passed: bool = False) -> dict[str, Any]:
    patch = self.get_gate_patch(patch_id)
    if not patch:
        raise ValueError("patch_id not found")
    approval = self._fetch_inserted(
        """
        insert into ai_gate_patch_approvals (patch_id, decision, note, approved_for_prod, strict_prod_policy_passed, actor)
        values (%(patch_id)s, 'approved', %(note)s, %(approved_for_prod)s, %(strict_prod_policy_passed)s, %(actor)s)
        returning approval_id, patch_id, decision, note, approved_for_prod, strict_prod_policy_passed, actor, created_at
        """,
        {
            "patch_id": patch_id,
            "note": note,
            "approved_for_prod": approved_for_prod,
            "strict_prod_policy_passed": strict_prod_policy_passed,
            "actor": actor,
        },
        {
            "approval_id": 1,
            "patch_id": patch_id,
            "decision": "approved",
            "note": note,
            "approved_for_prod": approved_for_prod,
            "strict_prod_policy_passed": strict_prod_policy_passed,
            "actor": actor,
        },
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set status = 'approved',
            approval_state = 'approved',
            last_transition_at = now()
        where patch_id = %(patch_id)s
        """,
        {"patch_id": patch_id},
    )
    self.save_patch_audit_log(
        patch_id=patch_id,
        event_type="patch_approved",
        status_from=str(patch.get("status")),
        status_to="approved",
        approval_state_from=str(patch.get("approval_state")),
        approval_state_to="approved",
        payload={"note": note, "approved_for_prod": approved_for_prod, "strict_prod_policy_passed": strict_prod_policy_passed},
        actor=actor,
    )
    updated = self.get_gate_patch(patch_id) or {}
    updated["approval"] = approval
    updated["audit_trail_count"] = len(self.get_gate_patch_audit(patch_id).get("audit_trail", []))
    return updated


def _reject_gate_patch(self, patch_id: int, *, actor: str | None = None, note: str | None = None) -> dict[str, Any]:
    patch = self.get_gate_patch(patch_id)
    if not patch:
        raise ValueError("patch_id not found")
    approval = self._fetch_inserted(
        """
        insert into ai_gate_patch_approvals (patch_id, decision, note, approved_for_prod, strict_prod_policy_passed, actor)
        values (%(patch_id)s, 'rejected', %(note)s, false, false, %(actor)s)
        returning approval_id, patch_id, decision, note, actor, created_at
        """,
        {"patch_id": patch_id, "note": note, "actor": actor},
        {"approval_id": 1, "patch_id": patch_id, "decision": "rejected", "note": note, "actor": actor},
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set status = 'rejected',
            approval_state = 'rejected',
            last_transition_at = now()
        where patch_id = %(patch_id)s
        """,
        {"patch_id": patch_id},
    )
    self.save_patch_audit_log(
        patch_id=patch_id,
        event_type="patch_rejected",
        status_from=str(patch.get("status")),
        status_to="rejected",
        approval_state_from=str(patch.get("approval_state")),
        approval_state_to="rejected",
        payload={"note": note},
        actor=actor,
    )
    updated = self.get_gate_patch(patch_id) or {}
    updated["approval"] = approval
    updated["audit_trail_count"] = len(self.get_gate_patch_audit(patch_id).get("audit_trail", []))
    return updated


def _get_gate_patch_audit(self, patch_id: int) -> dict[str, Any]:
    patch = self.get_gate_patch(patch_id)
    if not patch:
        raise ValueError("patch_id not found")
    approvals = self.executor.fetch_all(
        """
        select approval_id, patch_id, decision, note, approved_for_prod, strict_prod_policy_passed, actor, created_at
        from ai_gate_patch_approvals
        where patch_id = %(patch_id)s
        order by approval_id desc
        """,
        {"patch_id": patch_id},
    )
    audit = self.executor.fetch_all(
        """
        select audit_id, patch_id, event_type, status_from, status_to, approval_state_from, approval_state_to, payload_json, actor, created_at
        from ai_gate_patch_audit_logs
        where patch_id = %(patch_id)s
        order by audit_id desc
        """,
        {"patch_id": patch_id},
    )
    return {
        "patch": patch,
        "approvals": [self._decode_row(row) for row in approvals],
        "audit_trail": [self._decode_row(row) for row in audit],
        "audit_trail_count": len(audit),
    }


def _save_alert_state_action_v2(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    return self._fetch_inserted(
        """
        insert into ai_alert_state_actions (code, scope, status, note, muted_until, actor)
        values (%(code)s, %(scope)s, %(status)s, %(note)s, %(muted_until)s, %(actor)s)
        returning action_id, code, scope, status, note, muted_until, actor, created_at
        """,
        payload,
        {
            "action_id": 1,
            "code": payload["code"],
            "scope": payload.get("scope", "global"),
            "status": payload["status"],
            "note": payload.get("note"),
            "muted_until": payload.get("muted_until"),
            "actor": payload.get("actor"),
        },
    )


def _list_alert_state_actions_v2(self, *, code: str | None = None, scope: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if code:
        where.append("code = %(code)s")
        params["code"] = code
    if scope:
        where.append("scope = %(scope)s")
        params["scope"] = scope
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select action_id, code, scope, status, note, muted_until, actor, created_at
        from ai_alert_state_actions
        {where_sql}
        order by action_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "code": code, "scope": scope}


def _apply_gate_patch_v2(self, patch_id: int, *, actor: str | None = None) -> dict[str, Any]:
    patch = self.get_gate_patch(patch_id)
    if not patch:
        raise ValueError("patch_id not found")
    self.executor.execute(
        """
        insert into ai_strategy_gate_active_configs (strategy_code, active_patch_id, patch_json, rationale_ko, updated_by, scope_type, scope_key, patch_source)
        values (%(strategy_code)s, %(patch_id)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(updated_by)s, %(scope_type)s, %(scope_key)s, %(patch_source)s)
        on conflict (strategy_code) do update set
            active_patch_id = excluded.active_patch_id,
            patch_json = excluded.patch_json,
            rationale_ko = excluded.rationale_ko,
            updated_by = excluded.updated_by,
            updated_at = now(),
            scope_type = excluded.scope_type,
            scope_key = excluded.scope_key,
            patch_source = excluded.patch_source
        """,
        {
            "strategy_code": patch["strategy_code"],
            "patch_id": patch["patch_id"],
            "patch_json": self._json(patch.get("patch_json") or {}),
            "rationale_ko": patch.get("rationale_ko"),
            "updated_by": actor,
            "scope_type": patch.get("scope_type", "strategy_global"),
            "scope_key": patch.get("scope_key"),
            "patch_source": patch.get("patch_type", "manual"),
        },
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set applied = true,
            status = case when %(scope_type)s = 'strategy_global' then 'prod_active' else 'approved' end,
            last_transition_at = now()
        where patch_id = %(patch_id)s
        """,
        {"patch_id": patch_id, "scope_type": patch.get("scope_type", "strategy_global")},
    )
    self.save_patch_audit_log(
        patch_id=patch_id,
        event_type="patch_applied",
        status_from=str(patch.get("status")),
        status_to="prod_active" if patch.get("scope_type", "strategy_global") == "strategy_global" else str(patch.get("status")),
        approval_state_from=str(patch.get("approval_state")),
        approval_state_to=str(patch.get("approval_state")),
        payload={"scope_type": patch.get("scope_type")},
        actor=actor,
    )
    result = {
        "strategy_code": patch["strategy_code"],
        "active_patch_id": patch["patch_id"],
        "patch_json": patch.get("patch_json") or {},
        "rationale_ko": patch.get("rationale_ko"),
        "updated_by": actor,
        "applied": True,
        "status": "prod_active" if patch.get("scope_type", "strategy_global") == "strategy_global" else patch.get("status"),
        "approval_state": patch.get("approval_state"),
        "audit_trail_count": len(self.get_gate_patch_audit(patch_id).get("audit_trail", [])),
        "active_rollout_id": None,
    }
    return result


def _list_active_gate_configs_v2(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if strategy_code:
        where.append("strategy_code = %(strategy_code)s")
        params["strategy_code"] = strategy_code
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select strategy_code, active_patch_id, patch_json, rationale_ko, updated_by, updated_at, scope_type, scope_key, patch_source
        from ai_strategy_gate_active_configs
        {where_sql}
        order by updated_at desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "strategy_code": strategy_code}


def _rollback_active_gate_config_v2(self, strategy_code: str, *, target_patch_id: int, actor: str | None = None) -> dict[str, Any]:
    patch = self.get_gate_patch(target_patch_id)
    if not patch or str(patch.get("strategy_code")) != strategy_code:
        raise ValueError("target_patch_id not found for strategy_code")
    self.executor.execute(
        """
        insert into ai_strategy_gate_active_configs (strategy_code, active_patch_id, patch_json, rationale_ko, updated_by, scope_type, scope_key, patch_source)
        values (%(strategy_code)s, %(patch_id)s, %(patch_json)s::jsonb, %(rationale_ko)s, %(updated_by)s, %(scope_type)s, %(scope_key)s, %(patch_source)s)
        on conflict (strategy_code) do update set
            active_patch_id = excluded.active_patch_id,
            patch_json = excluded.patch_json,
            rationale_ko = excluded.rationale_ko,
            updated_by = excluded.updated_by,
            updated_at = now(),
            scope_type = excluded.scope_type,
            scope_key = excluded.scope_key,
            patch_source = excluded.patch_source
        """,
        {
            "strategy_code": strategy_code,
            "patch_id": patch["patch_id"],
            "patch_json": self._json(patch.get("patch_json") or {}),
            "rationale_ko": patch.get("rationale_ko"),
            "updated_by": actor,
            "scope_type": patch.get("scope_type", "strategy_global"),
            "scope_key": patch.get("scope_key"),
            "patch_source": patch.get("patch_type", "manual"),
        },
    )
    self.save_patch_audit_log(
        patch_id=target_patch_id,
        event_type="patch_rolled_back",
        status_from=str(patch.get("status")),
        status_to=str(patch.get("status")),
        approval_state_from=str(patch.get("approval_state")),
        approval_state_to=str(patch.get("approval_state")),
        payload={"strategy_code": strategy_code},
        actor=actor,
    )
    return {
        "strategy_code": strategy_code,
        "active_patch_id": patch["patch_id"],
        "patch_json": patch.get("patch_json") or {},
        "rationale_ko": patch.get("rationale_ko"),
        "updated_by": actor,
        "action": "rollback_to_patch",
        "status": patch.get("status"),
        "approval_state": patch.get("approval_state"),
    }


def _find_latest_patch(self, *, strategy_code: str, status: str | None = None, scope_type: str | None = None, exclude_patch_id: Any = None) -> dict[str, Any] | None:
    where = ["strategy_code = %(strategy_code)s"]
    params: dict[str, Any] = {"strategy_code": strategy_code}
    if status:
        where.append("status = %(status)s")
        params["status"] = status
    if scope_type:
        where.append("scope_type = %(scope_type)s")
        params["scope_type"] = scope_type
    if exclude_patch_id is not None:
        where.append("patch_id <> %(exclude_patch_id)s")
        params["exclude_patch_id"] = exclude_patch_id
    row = self.executor.fetch_one(
        f"""
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at,
               patch_type, scope_type, scope_key, regime, sector_code, market_cap_bucket, ticker, universe_profile,
               parent_patch_id, report_id, status, approval_state, last_transition_at
        from ai_strategy_gate_patches
        where {' and '.join(where)}
        order by patch_id desc
        limit 1
        """,
        params,
    )
    return self._decode_row(row)


def _create_rollout(self, *, patch_id: int, actor: str | None = None, note: str | None = None, report_id: str | None = None, initial_stage_pct: int = 10, mode: str = "semi-auto") -> dict[str, Any]:
    patch = self.get_gate_patch(patch_id)
    if not patch:
        raise ValueError("patch_id not found")
    if str(patch.get("approval_state")) not in {"approved", "auto_approved"}:
        raise ValueError("patch must be approved before rollout")
    status = "canary_active" if initial_stage_pct == 10 else "staged_active"
    saved = self._fetch_inserted(
        """
        insert into ai_gate_rollouts (patch_id, strategy_code, scope_type, scope_key, current_stage_pct, status, mode, report_id, created_by)
        values (%(patch_id)s, %(strategy_code)s, %(scope_type)s, %(scope_key)s, %(current_stage_pct)s, %(status)s, %(mode)s, %(report_id)s, %(created_by)s)
        returning rollout_id, patch_id, strategy_code, scope_type, scope_key, current_stage_pct, status, mode, report_id, approved_for_prod, strict_prod_policy_passed, created_by, created_at, updated_at
        """,
        {
            "patch_id": patch_id,
            "strategy_code": patch["strategy_code"],
            "scope_type": patch.get("scope_type", "strategy_global"),
            "scope_key": patch.get("scope_key"),
            "current_stage_pct": initial_stage_pct,
            "status": status,
            "mode": mode,
            "report_id": report_id or patch.get("report_id"),
            "created_by": actor,
        },
        {
            "rollout_id": 1,
            "patch_id": patch_id,
            "strategy_code": patch["strategy_code"],
            "scope_type": patch.get("scope_type", "strategy_global"),
            "scope_key": patch.get("scope_key"),
            "current_stage_pct": initial_stage_pct,
            "status": status,
            "mode": mode,
            "report_id": report_id or patch.get("report_id"),
            "created_by": actor,
        },
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set status = %(status)s,
            last_transition_at = now(),
            report_id = coalesce(%(report_id)s, report_id)
        where patch_id = %(patch_id)s
        """,
        {"status": status, "patch_id": patch_id, "report_id": report_id},
    )
    self.save_rollout_stage_event(
        rollout_id=int(saved["rollout_id"]),
        from_stage_pct=None,
        to_stage_pct=int(saved["current_stage_pct"]),
        event_type="rollout_created",
        verdict="started",
        payload={"note": note, "report_id": saved.get("report_id")},
        actor=actor,
    )
    self.save_patch_audit_log(
        patch_id=patch_id,
        event_type="rollout_started",
        status_from=str(patch.get("status")),
        status_to=status,
        approval_state_from=str(patch.get("approval_state")),
        approval_state_to=str(patch.get("approval_state")),
        payload={"rollout_id": saved["rollout_id"], "stage_pct": saved["current_stage_pct"]},
        actor=actor,
    )
    saved["active_rollout_id"] = saved.get("rollout_id")
    return saved


def _save_rollout_stage_event(self, *, rollout_id: int, from_stage_pct: int | None, to_stage_pct: int | None, event_type: str, verdict: str | None, payload: Mapping[str, Any] | None = None, actor: str | None = None) -> dict[str, Any]:
    return self._fetch_inserted(
        """
        insert into ai_gate_rollout_stage_events (rollout_id, from_stage_pct, to_stage_pct, event_type, verdict, payload_json, actor)
        values (%(rollout_id)s, %(from_stage_pct)s, %(to_stage_pct)s, %(event_type)s, %(verdict)s, %(payload_json)s::jsonb, %(actor)s)
        returning stage_event_id, rollout_id, from_stage_pct, to_stage_pct, event_type, verdict, payload_json, actor, created_at
        """,
        {
            "rollout_id": rollout_id,
            "from_stage_pct": from_stage_pct,
            "to_stage_pct": to_stage_pct,
            "event_type": event_type,
            "verdict": verdict,
            "payload_json": self._json(payload or {}),
            "actor": actor,
        },
        {
            "stage_event_id": 1,
            "rollout_id": rollout_id,
            "from_stage_pct": from_stage_pct,
            "to_stage_pct": to_stage_pct,
            "event_type": event_type,
            "verdict": verdict,
            "payload_json": payload or {},
            "actor": actor,
        },
    )


def _list_rollouts(self, *, strategy_code: str | None = None, status: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if strategy_code:
        where.append("strategy_code = %(strategy_code)s")
        params["strategy_code"] = strategy_code
    if status:
        if status == "active":
            where.append("status in ('canary_active', 'staged_active')")
        else:
            where.append("status = %(status)s")
            params["status"] = status
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select rollout_id, patch_id, strategy_code, scope_type, scope_key, current_stage_pct, status, mode, report_id,
               approved_for_prod, strict_prod_policy_passed, created_by, created_at, updated_at
        from ai_gate_rollouts
        {where_sql}
        order by rollout_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "strategy_code": strategy_code, "status": status}


def _get_rollout(self, rollout_id: int) -> dict[str, Any] | None:
    rollout = self.executor.fetch_one(
        """
        select rollout_id, patch_id, strategy_code, scope_type, scope_key, current_stage_pct, status, mode, report_id,
               approved_for_prod, strict_prod_policy_passed, created_by, created_at, updated_at
        from ai_gate_rollouts
        where rollout_id = %(rollout_id)s
        """,
        {"rollout_id": rollout_id},
    )
    decoded = self._decode_row(rollout)
    if not decoded:
        return None
    events = self.executor.fetch_all(
        """
        select stage_event_id, rollout_id, from_stage_pct, to_stage_pct, event_type, verdict, payload_json, actor, created_at
        from ai_gate_rollout_stage_events
        where rollout_id = %(rollout_id)s
        order by stage_event_id desc
        """,
        {"rollout_id": rollout_id},
    )
    decoded["stage_events"] = [self._decode_row(row) for row in events]
    return decoded


def _advance_rollout(self, *, rollout_id: int, to_stage_pct: int, actor: str | None = None, note: str | None = None, report_id: str | None = None, approved_for_prod: bool = False, strict_prod_policy_passed: bool = False) -> dict[str, Any]:
    rollout = self.get_rollout(rollout_id)
    if not rollout:
        raise ValueError("rollout_id not found")
    status = "prod_active" if to_stage_pct == 100 else "staged_active"
    self.executor.execute(
        """
        update ai_gate_rollouts
        set current_stage_pct = %(current_stage_pct)s,
            status = %(status)s,
            updated_at = now(),
            report_id = coalesce(%(report_id)s, report_id),
            approved_for_prod = approved_for_prod or %(approved_for_prod)s,
            strict_prod_policy_passed = strict_prod_policy_passed or %(strict_prod_policy_passed)s
        where rollout_id = %(rollout_id)s
        """,
        {
            "current_stage_pct": to_stage_pct,
            "status": status,
            "report_id": report_id,
            "approved_for_prod": approved_for_prod,
            "strict_prod_policy_passed": strict_prod_policy_passed,
            "rollout_id": rollout_id,
        },
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set status = %(status)s,
            report_id = coalesce(%(report_id)s, report_id),
            last_transition_at = now()
        where patch_id = %(patch_id)s
        """,
        {"status": status, "report_id": report_id, "patch_id": rollout["patch_id"]},
    )
    self.save_rollout_stage_event(
        rollout_id=rollout_id,
        from_stage_pct=int(rollout.get("current_stage_pct") or 0),
        to_stage_pct=to_stage_pct,
        event_type="rollout_advanced",
        verdict="passed",
        payload={"note": note, "report_id": report_id},
        actor=actor,
    )
    self.save_patch_audit_log(
        patch_id=int(rollout["patch_id"]),
        event_type="rollout_advanced",
        status_from=str(rollout.get("status")),
        status_to=status,
        approval_state_from=None,
        approval_state_to=None,
        payload={"rollout_id": rollout_id, "to_stage_pct": to_stage_pct},
        actor=actor,
    )
    return self.get_rollout(rollout_id) or {}


def _abort_rollout(self, rollout_id: int, *, actor: str | None = None, note: str | None = None) -> dict[str, Any]:
    rollout = self.get_rollout(rollout_id)
    if not rollout:
        raise ValueError("rollout_id not found")
    self.executor.execute(
        """
        update ai_gate_rollouts
        set status = 'aborted',
            updated_at = now()
        where rollout_id = %(rollout_id)s
        """,
        {"rollout_id": rollout_id},
    )
    self.executor.execute(
        """
        update ai_strategy_gate_patches
        set status = 'rolled_back',
            last_transition_at = now()
        where patch_id = %(patch_id)s
        """,
        {"patch_id": rollout["patch_id"]},
    )
    self.save_rollout_stage_event(
        rollout_id=rollout_id,
        from_stage_pct=int(rollout.get("current_stage_pct") or 0),
        to_stage_pct=int(rollout.get("current_stage_pct") or 0),
        event_type="rollout_aborted",
        verdict="aborted",
        payload={"note": note},
        actor=actor,
    )
    self.save_patch_audit_log(
        patch_id=int(rollout["patch_id"]),
        event_type="rollout_aborted",
        status_from=str(rollout.get("status")),
        status_to="rolled_back",
        approval_state_from=None,
        approval_state_to=None,
        payload={"rollout_id": rollout_id, "note": note},
        actor=actor,
    )
    return self.get_rollout(rollout_id) or {"rollout_id": rollout_id, "status": "aborted"}


def _set_control_state(self, *, control_type: str, enabled: bool, scope_type: str = "global", scope_key: str | None = None, note: str | None = None, actor: str | None = None) -> dict[str, Any]:
    existing = self.executor.fetch_one(
        """
        select control_state_id, control_type, enabled, scope_type, scope_key, note, actor, created_at, updated_at
        from ai_engine_control_states
        where control_type = %(control_type)s
          and scope_type = %(scope_type)s
          and (
              (%(scope_key)s is null and scope_key is null)
              or scope_key = %(scope_key)s
          )
        order by control_state_id desc
        limit 1
        """,
        {"control_type": control_type, "scope_type": scope_type, "scope_key": scope_key},
    )
    existing_decoded = self._decode_row(existing)
    if existing_decoded:
        self.executor.execute(
            """
            update ai_engine_control_states
            set enabled = %(enabled)s,
                note = %(note)s,
                actor = %(actor)s,
                updated_at = now()
            where control_state_id = %(control_state_id)s
            """,
            {"enabled": enabled, "note": note, "actor": actor, "control_state_id": existing_decoded["control_state_id"]},
        )
        control_state_id = existing_decoded["control_state_id"]
    else:
        inserted = self._fetch_inserted(
            """
            insert into ai_engine_control_states (control_type, enabled, scope_type, scope_key, note, actor)
            values (%(control_type)s, %(enabled)s, %(scope_type)s, %(scope_key)s, %(note)s, %(actor)s)
            returning control_state_id, control_type, enabled, scope_type, scope_key, note, actor, created_at, updated_at
            """,
            {"control_type": control_type, "enabled": enabled, "scope_type": scope_type, "scope_key": scope_key, "note": note, "actor": actor},
            {"control_state_id": 1, "control_type": control_type, "enabled": enabled, "scope_type": scope_type, "scope_key": scope_key, "note": note, "actor": actor},
        )
        control_state_id = inserted["control_state_id"]
    self.executor.execute(
        """
        insert into ai_engine_control_state_history (control_state_id, control_type, enabled, scope_type, scope_key, note, actor)
        values (%(control_state_id)s, %(control_type)s, %(enabled)s, %(scope_type)s, %(scope_key)s, %(note)s, %(actor)s)
        """,
        {
            "control_state_id": control_state_id,
            "control_type": control_type,
            "enabled": enabled,
            "scope_type": scope_type,
            "scope_key": scope_key,
            "note": note,
            "actor": actor,
        },
    )
    current = self.list_control_states(control_type=control_type, scope_type=scope_type, scope_key=scope_key)
    return current["items"][0] if current["items"] else {
        "control_state_id": control_state_id,
        "control_type": control_type,
        "enabled": enabled,
        "scope_type": scope_type,
        "scope_key": scope_key,
        "note": note,
        "actor": actor,
    }


def _list_control_states(self, *, control_type: str | None = None, scope_type: str | None = None, scope_key: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if control_type:
        where.append("control_type = %(control_type)s")
        params["control_type"] = control_type
    if scope_type:
        where.append("scope_type = %(scope_type)s")
        params["scope_type"] = scope_type
    if scope_key is not None:
        if scope_key == "":
            where.append("scope_key is null")
        else:
            where.append("scope_key = %(scope_key)s")
            params["scope_key"] = scope_key
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select control_state_id, control_type, enabled, scope_type, scope_key, note, actor, created_at, updated_at
        from ai_engine_control_states
        {where_sql}
        order by control_state_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset}


def _get_effective_control_states(self, *, strategy_code: str | None = None, universe_profile: str | None = None) -> list[dict[str, Any]]:
    rows = self.list_control_states(limit=500, offset=0).get("items", [])
    effective = []
    for row in rows:
        if not row.get("enabled"):
            continue
        scope_type = row.get("scope_type")
        scope_key = row.get("scope_key")
        if scope_type == "global":
            effective.append(row)
        elif scope_type == "strategy_code" and strategy_code and scope_key == strategy_code:
            effective.append(row)
        elif scope_type == "universe_profile" and universe_profile and scope_key == universe_profile:
            effective.append(row)
    return effective


def _resolve_active_patch(self, *, strategy_code: str, ticker: str | None = None, sector_code: str | None = None, market_cap_bucket: str | None = None, regime: str | None = None, universe_profile: str | None = None) -> dict[str, Any] | None:
    rows = self.executor.fetch_all(
        """
        select patch_id, strategy_code, patch_json, rationale_ko, source, applied, created_by, created_at,
               patch_type, scope_type, scope_key, regime, sector_code, market_cap_bucket, ticker, universe_profile,
               parent_patch_id, report_id, status, approval_state, last_transition_at
        from ai_strategy_gate_patches
        where strategy_code = %(strategy_code)s
          and status in ('prod_active', 'approved')
        order by patch_id desc
        """,
        {"strategy_code": strategy_code},
    )
    decoded = [self._decode_row(row) or {} for row in rows]
    precedence = [
        ("strategy_ticker", lambda item: ticker and item.get("ticker") == ticker),
        ("strategy_sector_cap", lambda item: sector_code and market_cap_bucket and item.get("sector_code") == sector_code and item.get("market_cap_bucket") == market_cap_bucket),
        ("strategy_sector", lambda item: sector_code and item.get("sector_code") == sector_code),
        ("strategy_regime", lambda item: regime and item.get("regime") == regime),
        ("strategy_global", lambda item: True),
    ]
    for scope_type, matcher in precedence:
        for item in decoded:
            if item.get("scope_type") == scope_type and matcher(item):
                return item
    active_rows = self.list_active_gate_configs(strategy_code=strategy_code, limit=1, offset=0).get("items", [])
    return active_rows[0] if active_rows else None


def _save_regression_report(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    return self._fetch_inserted(
        """
        insert into ai_regression_reports (
            report_id, suite_name, strategy_code, baseline_patch_id, candidate_patch_id, overall_json, strategy_delta_json,
            regime_delta_json, sector_delta_json, market_cap_delta_json, markdown_text, verdict, promotion_recommendation,
            closed_replay_sample, created_by
        ) values (
            %(report_id)s, %(suite_name)s, %(strategy_code)s, %(baseline_patch_id)s, %(candidate_patch_id)s, %(overall_json)s::jsonb, %(strategy_delta_json)s::jsonb,
            %(regime_delta_json)s::jsonb, %(sector_delta_json)s::jsonb, %(market_cap_delta_json)s::jsonb, %(markdown_text)s, %(verdict)s, %(promotion_recommendation)s,
            %(closed_replay_sample)s, %(created_by)s
        )
        on conflict (report_id) do update set
            overall_json = excluded.overall_json,
            strategy_delta_json = excluded.strategy_delta_json,
            regime_delta_json = excluded.regime_delta_json,
            sector_delta_json = excluded.sector_delta_json,
            market_cap_delta_json = excluded.market_cap_delta_json,
            markdown_text = excluded.markdown_text,
            verdict = excluded.verdict,
            promotion_recommendation = excluded.promotion_recommendation,
            closed_replay_sample = excluded.closed_replay_sample,
            created_by = excluded.created_by
        returning report_id, suite_name, strategy_code, baseline_patch_id, candidate_patch_id, overall_json, strategy_delta_json,
                  regime_delta_json, sector_delta_json, market_cap_delta_json, markdown_text, verdict, promotion_recommendation,
                  closed_replay_sample, created_by, created_at
        """,
        {
            "report_id": payload["report_id"],
            "suite_name": payload["suite_name"],
            "strategy_code": payload["strategy_code"],
            "baseline_patch_id": payload.get("baseline_patch_id"),
            "candidate_patch_id": payload.get("candidate_patch_id"),
            "overall_json": self._json(payload.get("overall") or {}),
            "strategy_delta_json": self._json(payload.get("strategy_delta") or {}),
            "regime_delta_json": self._json(payload.get("regime_delta") or {}),
            "sector_delta_json": self._json(payload.get("sector_delta") or {}),
            "market_cap_delta_json": self._json(payload.get("market_cap_delta") or {}),
            "markdown_text": payload.get("markdown_text"),
            "verdict": payload["verdict"],
            "promotion_recommendation": payload["promotion_recommendation"],
            "closed_replay_sample": payload.get("closed_replay_sample", 0),
            "created_by": payload.get("created_by"),
        },
        dict(payload),
    )


def _list_regression_reports(self, *, strategy_code: str | None = None, suite_name: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if strategy_code:
        where.append("strategy_code = %(strategy_code)s")
        params["strategy_code"] = strategy_code
    if suite_name:
        where.append("suite_name = %(suite_name)s")
        params["suite_name"] = suite_name
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select report_id, suite_name, strategy_code, baseline_patch_id, candidate_patch_id, overall_json, strategy_delta_json,
               regime_delta_json, sector_delta_json, market_cap_delta_json, markdown_text, verdict, promotion_recommendation,
               closed_replay_sample, created_by, created_at
        from ai_regression_reports
        {where_sql}
        order by created_at desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "strategy_code": strategy_code, "suite_name": suite_name}


def _get_regression_report(self, report_id: str) -> dict[str, Any] | None:
    row = self.executor.fetch_one(
        """
        select report_id, suite_name, strategy_code, baseline_patch_id, candidate_patch_id, overall_json, strategy_delta_json,
               regime_delta_json, sector_delta_json, market_cap_delta_json, markdown_text, verdict, promotion_recommendation,
               closed_replay_sample, created_by, created_at
        from ai_regression_reports
        where report_id = %(report_id)s
        """,
        {"report_id": report_id},
    )
    return self._decode_row(row)


def _save_calibration_proposal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    return self._fetch_inserted(
        """
        insert into ai_calibration_proposals (patch_id, strategy_code, segment_type, segment_key, report_id, proposal_json, summary_json, created_by)
        values (%(patch_id)s, %(strategy_code)s, %(segment_type)s, %(segment_key)s, %(report_id)s, %(proposal_json)s::jsonb, %(summary_json)s::jsonb, %(created_by)s)
        returning proposal_id, patch_id, strategy_code, segment_type, segment_key, report_id, proposal_json, summary_json, created_by, promoted, created_at
        """,
        {
            "patch_id": payload["patch_id"],
            "strategy_code": payload["strategy_code"],
            "segment_type": payload["segment_type"],
            "segment_key": payload["segment_key"],
            "report_id": payload.get("report_id"),
            "proposal_json": self._json(payload.get("proposal_json") or {}),
            "summary_json": self._json(payload.get("summary_json") or {}),
            "created_by": payload.get("created_by"),
        },
        {
            "proposal_id": 1,
            "patch_id": payload["patch_id"],
            "strategy_code": payload["strategy_code"],
            "segment_type": payload["segment_type"],
            "segment_key": payload["segment_key"],
            "report_id": payload.get("report_id"),
            "proposal_json": payload.get("proposal_json") or {},
            "summary_json": payload.get("summary_json") or {},
            "created_by": payload.get("created_by"),
            "promoted": False,
        },
    )


def _list_calibration_proposals(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    where = []
    params = {"limit": limit, "offset": offset}
    if strategy_code:
        where.append("strategy_code = %(strategy_code)s")
        params["strategy_code"] = strategy_code
    where_sql = ("where " + " and ".join(where)) if where else ""
    rows = self.executor.fetch_all(
        f"""
        select proposal_id, patch_id, strategy_code, segment_type, segment_key, report_id, proposal_json, summary_json, created_by, promoted, created_at
        from ai_calibration_proposals
        {where_sql}
        order by proposal_id desc
        limit %(limit)s offset %(offset)s
        """,
        params,
    )
    return {"items": [self._decode_row(r) for r in rows], "limit": limit, "offset": offset, "strategy_code": strategy_code}


def _get_calibration_proposal(self, proposal_id: int) -> dict[str, Any] | None:
    row = self.executor.fetch_one(
        """
        select proposal_id, patch_id, strategy_code, segment_type, segment_key, report_id, proposal_json, summary_json, created_by, promoted, created_at
        from ai_calibration_proposals
        where proposal_id = %(proposal_id)s
        """,
        {"proposal_id": proposal_id},
    )
    return self._decode_row(row)


def _mark_calibration_proposal_promoted(self, proposal_id: int, *, actor: str | None = None) -> dict[str, Any]:
    self.executor.execute(
        """
        update ai_calibration_proposals
        set promoted = true
        where proposal_id = %(proposal_id)s
        """,
        {"proposal_id": proposal_id},
    )
    proposal = self.get_calibration_proposal(proposal_id)
    if proposal and proposal.get("patch_id"):
        self.save_patch_audit_log(
            patch_id=int(proposal["patch_id"]),
            event_type="calibration_promote_requested",
            status_from=None,
            status_to=None,
            approval_state_from=None,
            approval_state_to=None,
            payload={"proposal_id": proposal_id},
            actor=actor,
        )
    return proposal or {"proposal_id": proposal_id, "promoted": True}


def _save_hold_tuning_snapshot(self, *, strategy_code: str, segment_type: str, segment_key: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return self._fetch_inserted(
        """
        insert into ai_hold_tuning_snapshots (
            strategy_code, segment_type, segment_key, expected_mfe_mae_ratio, time_to_peak_ewma, time_to_fail_ewma, sample_size
        ) values (
            %(strategy_code)s, %(segment_type)s, %(segment_key)s, %(expected_mfe_mae_ratio)s, %(time_to_peak_ewma)s, %(time_to_fail_ewma)s, %(sample_size)s
        )
        returning snapshot_id, strategy_code, segment_type, segment_key, expected_mfe_mae_ratio, time_to_peak_ewma, time_to_fail_ewma, sample_size, as_of_date, created_at
        """,
        {
            "strategy_code": strategy_code,
            "segment_type": segment_type,
            "segment_key": segment_key,
            "expected_mfe_mae_ratio": snapshot.get("expected_mfe_mae_ratio"),
            "time_to_peak_ewma": snapshot.get("time_to_peak_ewma"),
            "time_to_fail_ewma": snapshot.get("time_to_fail_ewma"),
            "sample_size": snapshot.get("sample_size", 0),
        },
        {
            "snapshot_id": 1,
            "strategy_code": strategy_code,
            "segment_type": segment_type,
            "segment_key": segment_key,
            **dict(snapshot),
        },
    )


def _compute_hold_tuning_snapshot(self, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"expected_mfe_mae_ratio": 0.0, "time_to_peak_ewma": 1.0, "time_to_fail_ewma": 1.0, "sample_size": 0}
    sample_size = len(rows)
    ratios = []
    time_to_peak = []
    time_to_fail = []
    for row in rows:
        mfe = abs(float(row.get("mfe_pct") or 0.0))
        mae = abs(float(row.get("mae_pct") or 0.0))
        ratios.append(mfe / max(mae, 0.25))
        milestones = row.get("milestones") if isinstance(row.get("milestones"), list) else []
        if milestones:
            peak_day = 1
            fail_day = 1
            for milestone in milestones:
                day_text = str(milestone.get("day") or "D+1").replace("D+", "")
                try:
                    day_value = float(day_text)
                except ValueError:
                    day_value = 1.0
                if "tp" in str(milestone.get("status") or "").lower():
                    peak_day = day_value
                    break
                fail_day = day_value
            time_to_peak.append(peak_day)
            time_to_fail.append(fail_day)
        else:
            hold_days = float(row.get("hold_days") or 1.0)
            time_to_peak.append(max(1.0, hold_days / 2.0))
            time_to_fail.append(max(1.0, hold_days))
    return {
        "expected_mfe_mae_ratio": round(sum(ratios) / sample_size, 4),
        "time_to_peak_ewma": round(sum(time_to_peak) / sample_size, 4),
        "time_to_fail_ewma": round(sum(time_to_fail) / sample_size, 4),
        "sample_size": sample_size,
    }


def _get_closed_replay_samples(self, *, strategy_code: str, lookback_days: int = 180) -> list[dict[str, Any]]:
    rows = self.executor.fetch_all(
        """
        select
            r.run_id,
            r.strategy_code,
            r.direction,
            r.magnitude,
            r.confidence,
            r.hold_days,
            r.raw_analysis_json,
            e.ticker,
            e.sector,
            e.event_time,
            fs.market_snapshot_json,
            rp.realized_pnl_pct,
            rp.mfe_pct,
            rp.mae_pct,
            rp.milestones_json
        from ai_analysis_runs r
        join ai_events e on e.event_id = r.event_id
        left join ai_feature_snapshots fs on fs.run_id = r.run_id
        left join ai_replay_tracks rp on rp.run_id = r.run_id
        where r.strategy_code = %(strategy_code)s
          and rp.status = 'closed'
          and r.created_at >= now() - make_interval(days => %(lookback_days)s)
        order by e.event_time asc
        """,
        {"strategy_code": strategy_code, "lookback_days": lookback_days},
    )
    samples: list[dict[str, Any]] = []
    for row in rows:
        decoded = self._decode_row(row) or {}
        raw = decoded.get("raw_analysis_json") if isinstance(decoded.get("raw_analysis_json"), Mapping) else {}
        market_snapshot = decoded.get("market_snapshot_json") if isinstance(decoded.get("market_snapshot_json"), Mapping) else {}
        samples.append(
            {
                "run_id": decoded.get("run_id"),
                "strategy_code": decoded.get("strategy_code"),
                "ticker": decoded.get("ticker"),
                "sector": decoded.get("sector"),
                "sector_code": market_snapshot.get("sector_code") or decoded.get("sector"),
                "market_cap": market_snapshot.get("market_cap"),
                "market_cap_bucket": market_snapshot.get("market_cap_bucket") or self.normalize_market_cap_bucket(market_snapshot.get("market_cap")),
                "event_time": decoded.get("event_time"),
                "confidence": decoded.get("confidence"),
                "magnitude": decoded.get("magnitude"),
                "strategy_score": raw.get("metadata", {}).get("strategy_score") if isinstance(raw.get("metadata"), Mapping) else raw.get("strategy_score"),
                "volume_ratio": market_snapshot.get("volume_ratio"),
                "event_quality": self.extract_event_quality(raw if isinstance(raw, Mapping) else {}),
                "gap_overshoot": 0.0 if market_snapshot.get("implied_move_pct") is None else max(0.0, abs(float(market_snapshot.get("gap_pct") or 0.0)) - abs(float(market_snapshot.get("implied_move_pct") or 0.0))),
                "realized_pnl_pct": decoded.get("realized_pnl_pct"),
                "mfe_pct": decoded.get("mfe_pct"),
                "mae_pct": decoded.get("mae_pct"),
                "milestones": decoded.get("milestones_json") or [],
                "hold_days": decoded.get("hold_days"),
                "regime": "high_vol" if float(market_snapshot.get("vix") or 0.0) >= 25.0 else "normal",
            }
        )
    return samples


EventStoreRepository.normalize_market_cap_bucket = _normalize_market_cap_bucket
EventStoreRepository.materialize_thresholds = _materialize_thresholds
EventStoreRepository.extract_event_quality = _extract_event_quality
EventStoreRepository.compute_gap_overshoot = _compute_gap_overshoot
EventStoreRepository._fetch_inserted = _fetch_inserted
EventStoreRepository.save_patch_audit_log = _save_patch_audit_log
EventStoreRepository.get_gate_patch = _get_gate_patch
EventStoreRepository.save_gate_patch = _save_gate_patch_v2
EventStoreRepository.list_gate_patches = _list_gate_patches_v2
EventStoreRepository.approve_gate_patch = _approve_gate_patch
EventStoreRepository.reject_gate_patch = _reject_gate_patch
EventStoreRepository.get_gate_patch_audit = _get_gate_patch_audit
EventStoreRepository.save_alert_state_action = _save_alert_state_action_v2
EventStoreRepository.list_alert_state_actions = _list_alert_state_actions_v2
EventStoreRepository.apply_gate_patch = _apply_gate_patch_v2
EventStoreRepository.list_active_gate_configs = _list_active_gate_configs_v2
EventStoreRepository.rollback_active_gate_config = _rollback_active_gate_config_v2
EventStoreRepository.find_latest_patch = _find_latest_patch
EventStoreRepository.create_rollout = _create_rollout
EventStoreRepository.save_rollout_stage_event = _save_rollout_stage_event
EventStoreRepository.list_rollouts = _list_rollouts
EventStoreRepository.get_rollout = _get_rollout
EventStoreRepository.advance_rollout = _advance_rollout
EventStoreRepository.abort_rollout = _abort_rollout
EventStoreRepository.set_control_state = _set_control_state
EventStoreRepository.list_control_states = _list_control_states
EventStoreRepository.get_effective_control_states = _get_effective_control_states
EventStoreRepository.resolve_active_patch = _resolve_active_patch
EventStoreRepository.save_regression_report = _save_regression_report
EventStoreRepository.list_regression_reports = _list_regression_reports
EventStoreRepository.get_regression_report = _get_regression_report
EventStoreRepository.save_calibration_proposal = _save_calibration_proposal
EventStoreRepository.list_calibration_proposals = _list_calibration_proposals
EventStoreRepository.get_calibration_proposal = _get_calibration_proposal
EventStoreRepository.mark_calibration_proposal_promoted = _mark_calibration_proposal_promoted
EventStoreRepository.save_hold_tuning_snapshot = _save_hold_tuning_snapshot
EventStoreRepository.compute_hold_tuning_snapshot = _compute_hold_tuning_snapshot
EventStoreRepository.get_closed_replay_samples = _get_closed_replay_samples


__all__ = ["PersistResult", "ReplayUpdateResult", "EventStoreRepository"]
