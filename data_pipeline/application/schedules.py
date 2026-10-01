"""Refresh dates, reconcile sources and verify official IR evidence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from zoneinfo import ZoneInfo
from ..collectors import CollectorChain
from ..collectors.schedules import NasdaqEarningsCalendar, YFinanceScheduleStrategy
from ..collectors.schedules.enricher import OfficialScheduleEnricher
from .settings import env_bool, env_int


class ScheduleService:
    def __init__(self, repository, health, *, schedule_chain=None,
                 enricher_factory=OfficialScheduleEnricher,
                 calendar_factory=NasdaqEarningsCalendar):
        self.repository = repository
        self.health = health
        self.schedule_chain = schedule_chain if schedule_chain is not None else CollectorChain([YFinanceScheduleStrategy()])
        self.enricher_factory = enricher_factory
        self.calendar_factory = calendar_factory

    def _fetch_single_schedule(self, ticker):
        """멀티쓰레딩용 개별 일정 수집 작업"""
        try:
            return self.schedule_chain.execute(ticker)
        except Exception as e:
            print(f"❌ {ticker} 일정 수집 중 오류: {e}")
            return None


    def update_all_schedules(self, max_workers=10):
        """[Phase 2] 전 종목의 어닝 일정 병렬 수집"""
        # MySQL DATETIME stores seconds, not Python microseconds.  Use the
        # same precision for the observation marker so a just-saved Yahoo row
        # is never mistaken for a disappeared source row during reconciliation.
        observed_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        print(f"\n[Step 2] 전 종목 어닝 일정 병렬 수집 시작 (쓰레드: {max_workers}개)...")
        tickers = self.repository.get_all_tickers()
        if not tickers:
            return observed_at

        all_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {executor.submit(self._fetch_single_schedule, t): t for t in tickers}
            for future in as_completed(future_to_ticker):
                result = future.result()
                if result: all_results.extend(result)
        
        if all_results:
            self.repository.save_earnings_schedules(all_results, observed_at=observed_at)
            print(f"✅ 총 {len(all_results)}개의 일정을 DB에 동기화했습니다.")
        return observed_at


    def reconcile_near_term_schedule_sources(
        self,
        *,
        yahoo_observed_at: datetime,
    ) -> dict[str, int]:
        """Cross-check Yahoo's near-term rows before a watcher can claim them."""
        if not env_bool("SCHEDULE_NASDAQ_RECONCILIATION_ENABLED", True):
            return {
                "nasdaq_events": 0,
                "source_matches": 0,
                "source_recovered": 0,
                "date_mismatches": 0,
                "yahoo_missing": 0,
                "nasdaq_only": 0,
            }

        days_ahead = env_int(
            "SCHEDULE_RECONCILIATION_DAYS_AHEAD",
            14,
        )
        event_timezone = ZoneInfo(
            os.getenv("DATE_STREAM_WATCH_TIMEZONE", "America/New_York")
        )
        start_date = datetime.now(event_timezone).date()
        result = self.calendar_factory(
            timeout_seconds=env_int(
                "SCHEDULE_NASDAQ_TIMEOUT_SECONDS",
                15,
            )
        ).collect(
            start_date=start_date,
            days_ahead=days_ahead,
            tickers=self.repository.get_all_tickers(),
        )
        if not result.fetched_dates:
            print(
                "[ScheduleReconcile] Nasdaq calendar unavailable; "
                "skipping absence-based revalidation.",
                flush=True,
            )
            self.health.record_event(
                "schedule_reconciliation",
                status="nasdaq_unavailable",
                days_ahead=days_ahead,
                failed_dates=len(result.failed_dates),
            )
            return {
                "nasdaq_events": 0,
                "source_matches": 0,
                "source_recovered": 0,
                "date_mismatches": 0,
                "yahoo_missing": 0,
                "nasdaq_only": 0,
            }

        summary = self.repository.reconcile_near_term_schedule_sources(
            result.schedules,
            yahoo_observed_at=yahoo_observed_at,
            nasdaq_fetched_dates=result.fetched_dates,
            start_date=start_date,
            days_ahead=days_ahead,
        )
        self.health.record_event(
            "schedule_reconciliation",
            status="completed",
            days_ahead=days_ahead,
            fetched_dates=len(result.fetched_dates),
            failed_dates=len(result.failed_dates),
            **summary,
        )
        print(
            "[ScheduleReconcile] "
            f"matched={summary['source_matches']} "
            f"source_recovered={summary['source_recovered']} "
            f"date_mismatches={summary['date_mismatches']} "
            f"yahoo_missing={summary['yahoo_missing']} "
            f"nasdaq_only={summary['nasdaq_only']} "
            f"failed_dates={len(result.failed_dates)}",
            flush=True,
        )
        return summary


    def enrich_schedule_times(self, limit: int = 20):
        """Refresh exact starts in DB; nearby unresolved rows get bounded browser reads.

        Reusing this one enricher shares its browser time/page budget across the
        batch. The broad calendar window still uses inexpensive HTTP first.
        """
        days_ahead = env_int(
            "SCHEDULE_TIME_REVERIFY_DAYS_AHEAD",
            14,
        )
        calls = self.repository.get_calls_missing_verified_time(
            limit=limit,
            days_ahead=days_ahead,
        )
        if not calls:
            print("[ScheduleTime] No unverified future calls to process.")
            return

        enricher = self.enricher_factory()
        verified_count = 0
        failed_count = 0
        for call in calls:
            try:
                verified = enricher.verify_call(call)
            except Exception as exc:
                # One malformed issuer page must not leave every later company
                # unprocessed during startup or the recurring schedule refresh.
                failed_count += 1
                self.health.record_event(
                    "schedule_enrichment",
                    ticker=call.get("ticker"),
                    call_id=call.get("id"),
                    status="failed",
                    error_type=type(exc).__name__,
                )
                print(
                    f"[ScheduleTime] {call.get('ticker')} enrichment failed: "
                    f"{type(exc).__name__}; continuing remaining calls",
                    flush=True,
                )
                continue
            if verified:
                verified_count += 1
                print(
                    f"[ScheduleTime] {call['ticker']} verified "
                    f"{verified.scheduled_at_utc.isoformat()}"
                )
            else:
                print(f"[ScheduleTime] {call['ticker']} remains unverified")
            evidence = getattr(enricher, 'last_dry_run', None)
            if isinstance(evidence, dict):
                self.health.record_event(
                    'schedule_enrichment', ticker=call.get('ticker'), call_id=call.get('id'),
                    status='verified' if verified else 'unverified',
                    scheduled_at_utc=verified.scheduled_at_utc.isoformat() if verified else None,
                    source=getattr(verified, 'schedule_source', None),
                    pages_checked=len(evidence.get('pages_checked', [])),
                    browser_pages=evidence.get('browser_pages', 0),
                    browser_seconds=evidence.get('browser_seconds', 0),
                    browser_skipped=evidence.get('browser_skipped', []),
                    conflicted=bool(evidence.get('conflicted')),
                    conflicts=evidence.get('conflicts', []),
                    route_decisions=evidence.get('route_diagnostics', []),
                    route_recovery_reasons=sorted({item.get('reason') for item in
                        evidence.get('route_diagnostics', []) if item.get('reason')}),
                    has_event_route=bool((evidence.get('discovery') or {}).get('event_url')),
                    has_webcast_route=bool((evidence.get('discovery') or {}).get('webcast_url')),
                    issuer_failure_kinds=sorted({item.get('kind') for item in
                        evidence.get('failures', []) if item.get('kind')}),
                    unavailable_statuses=evidence.get('unavailable_statuses', []),
                )

        print(
            f"[ScheduleTime] Verified {verified_count}/{len(calls)} calls; "
            f"failed={failed_count}."
        )


    def refresh_live_schedule_data(self):
        """Refresh broad dates first, then enrich a bounded set of exact times."""
        workers = env_int("LIVE_SCHEDULE_REFRESH_WORKERS", 10)
        limit = env_int("SCHEDULE_TIME_REFRESH_LIMIT", 20)
        yahoo_observed_at = self.update_all_schedules(max_workers=workers)
        self.reconcile_near_term_schedule_sources(
            yahoo_observed_at=yahoo_observed_at,
        )
        self.enrich_schedule_times(limit=limit)


    def _refresh_single_live_call_schedule(self, call_id: int, ticker: str) -> bool:
        """Refresh one stale candidate before spending another browser probe on it."""
        schedules = self._fetch_single_schedule(ticker)
        if schedules:
            self.repository.save_earnings_schedules(schedules)

        refreshed = self.repository.get_call_schedule_context(call_id)
        if not refreshed:
            return False
        # Re-use issuer-owned pages first. This is intentionally one call, not
        # a broad refresh of every ticker after a single candidate mismatch.
        self.enricher_factory().verify_call(refreshed)
        return True


    async def _refresh_schedule_after_probe_mismatch(
        self,
        call_id: int,
        ticker: str,
        error: str | None,
    ) -> None:
        if not self.repository.request_schedule_refresh(call_id, error):
            return
        try:
            refreshed = await asyncio.to_thread(
                self._refresh_single_live_call_schedule,
                call_id,
                ticker,
            )
            self.repository.record_schedule_refresh_outcome(
                call_id,
                success=bool(refreshed),
                error=None if refreshed else "call disappeared during targeted schedule refresh",
            )
            self.health.record_event(
                "schedule_refresh",
                ticker=ticker,
                call_id=call_id,
                status="refreshed" if refreshed else "missing",
                error=error,
            )
        except Exception as exc:
            self.repository.record_schedule_refresh_outcome(
                call_id,
                success=False,
                error=str(exc),
            )
            self.health.record_event(
                "schedule_refresh",
                ticker=ticker,
                call_id=call_id,
                status="failed",
                error=str(exc),
            )
            print(f"[ScheduleTime] targeted refresh failed ticker={ticker}: {exc}")
