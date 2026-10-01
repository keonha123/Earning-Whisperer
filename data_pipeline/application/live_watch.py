"""Select due calls, dispatch browser probes and hand off verified capture."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from sqlalchemy.exc import SQLAlchemyError
from ..stt_worker.manager import STTWorkerManager
from .. import live_runtime
from ..failure_reasons import classify_live_failure
from ..collectors.schedules.browser_observation import validated_browser_values, browser_clock_changed
from .settings import (
    capture_runtime_environment,
    env_int,
    maintenance_window_active,
    probe_window,
)


class LiveWatchService:
    def __init__(self, repository, worker_manager, schedules, health):
        self.repository = repository
        self.worker_manager = worker_manager
        self.schedules = schedules
        self.health = health
        self._date_stream_dispatch_lock: asyncio.Lock | None = None
        self._date_stream_background_tasks: dict[int, asyncio.Task[Any]] = {}
        self._date_stream_candidate_query_failed = False
        self._capture_reservations: set[str] = set()
        self._preparing_call_ids: set[int] = set()

    def _record_probe(self, call_id, *, call=None, **kwargs):
        """One completion path for probe state and authenticated clock evidence."""
        values = validated_browser_values(call, call.get('_browser_schedule_observation')) if call else None
        if values:
            kwargs['schedule_observation'] = values
        if call and call.get('schedule_revision') is not None:
            kwargs['expected_schedule_revision'] = int(call['schedule_revision'])
        result = self.repository.record_stream_probe(call_id, **kwargs)
        if values and isinstance(result, dict):
            applied = bool(result.get('schedule_applied'))
            conflict_retained = result.get('accepted') is True and result.get('schedule_conflicted') is True
            context = result.get('schedule_context') or {}
            # A durable disagreement deliberately leaves the exact clock unset.
            # That is successful evidence retention, not a rejected DB write.
            diagnostic = ({'clock_conflict_retained': True,
                'clock_source_count': len(result.get('clock_observations') or []),
                'missing_clock_source_count': len(result.get('missing_clock_sources') or [])}
                if conflict_retained else {})
            self.health.record_event('browser_clock_conflict_retained' if conflict_retained else 'browser_schedule_time',
                call_id=call_id, ticker=call.get('ticker'),
                status='provisional_watch' if conflict_retained else 'saved' if applied else 'stale_or_rejected',
                scheduled_at_utc=context.get('scheduled_at_utc'),
                schedule_revision=context.get('schedule_revision'),
                source=values['schedule_source'], changed=result.get('schedule_changed', False), **diagnostic)
            live_runtime.record(call, 'schedule', 'browser_clock_conflict_retained' if conflict_retained
                else 'browser_start_committed' if applied else 'browser_start_rejected',
                status='provisional_watch' if conflict_retained else 'saved' if applied else 'rejected', progress=applied,
                scheduled_at_utc=context.get('scheduled_at_utc'),
                committed_revision=context.get('schedule_revision'), **diagnostic)
        return result

    async def monitor_and_trigger_stt(self):
        """
        [Phase 4] 정확한 시작 시각이 있는 기존 경로의 워커 실행 로직.
        매 분마다 호출되어 DB를 확인하고, 임박한 일정이 있다면 워커를 깨웁니다.
        """
        # 시각적인 확인을 위해 현재 감시 중임을 표시합니다. (운영 시에는 선택 사항)
        # print(f"🔍 [Monitor] {datetime.now().strftime('%H:%M:%S')} 어닝콜 일정 스캔 중...")

        try:
            imminent_calls = self.repository.get_imminent_calls(minutes_ahead=5, grace_minutes=1)

            if not imminent_calls:
                return

            for call in imminent_calls:
                call_id = call.get('id')
                ticker = call.get('ticker')
                call = dict(call)
                capture_session_id = STTWorkerManager.build_capture_session_id(call)
                call["_capture_session_id"] = capture_session_id
                
                print(f"🚀 [Orchestrator] {ticker} 어닝콜 임박 감지! 워커 배정을 시작합니다.")

                if not self.repository.mark_call_running(
                    call_id,
                    capture_session_id=capture_session_id,
                ):
                    print(f"↪️ [Orchestrator] {ticker}는 이미 다른 워커가 처리 중입니다.")
                    continue

                try:
                    await self.worker_manager.launch_mission(call)
                except Exception as worker_error:
                    self.repository.requeue_failed_call_capture(
                        call_id,
                        error=str(worker_error),
                        capture_session_id=capture_session_id,
                    )
                    print(f"❌ [Orchestrator] {ticker} 워커 실행 실패: {worker_error}")

        except Exception as e:
            print(f"❌ [Monitor Error] 감시 로직 실행 중 오류 발생: {e}")


    def _date_stream_settings(self) -> dict[str, int]:
        return {
            "days_ahead": env_int("DATE_STREAM_WATCH_DAYS_AHEAD", 2, 0),
            "batch_size": env_int("DATE_STREAM_WATCH_BATCH_SIZE", 10),
            "cooldown_minutes": env_int(
                "DATE_STREAM_WATCH_COOLDOWN_MINUTES", 1
            ),
            "near_start_minutes": env_int(
                "DATE_STREAM_NEAR_START_MINUTES", 20, 0
            ),
            "near_end_minutes": env_int(
                "DATE_STREAM_NEAR_END_MINUTES", 180, 0
            ),
            "near_cooldown_minutes": env_int(
                "DATE_STREAM_NEAR_INTERVAL_MINUTES", 1
            ),
            "concurrency": env_int("DATE_STREAM_WATCH_CONCURRENCY", 3),
            "discovery_concurrency": env_int("DATE_STREAM_DISCOVERY_CONCURRENCY", 2),
            "capture_concurrency": env_int("DATE_STREAM_CAPTURE_CONCURRENCY",
                                            env_int("DATE_STREAM_WATCH_CONCURRENCY", 3)),
        }


    def _active_date_stream_captures(self) -> int:
        """Count long-running browser/STT jobs against the live watch budget."""
        counter = getattr(self.worker_manager, "active_capture_count", None)
        if callable(counter):
            return max(0, int(counter()))
        # Test and legacy worker doubles may not expose the public helper.
        processes = getattr(self.worker_manager, "_active_processes", {})
        return sum(
            getattr(process, "returncode", None) is None
            for process in processes.values()
        )


    def _date_stream_candidates(self, settings: dict[str, int]) -> list[dict[str, Any]]:
        self._date_stream_candidate_query_failed = False
        configured_tickers = {
            ticker.strip().upper().replace(".", "-")
            for ticker in os.getenv("DATE_STREAM_WATCH_TICKERS", "").split(",")
            if ticker.strip()
        }
        try:
            candidates = self.repository.get_date_based_stream_candidates(
                days_ahead=settings["days_ahead"],
                limit=settings["batch_size"],
                cooldown_minutes=settings["cooldown_minutes"],
                near_start_minutes=settings["near_start_minutes"],
                near_end_minutes=settings["near_end_minutes"],
                near_cooldown_minutes=settings["near_cooldown_minutes"],
                **({"tickers": sorted(configured_tickers)} if configured_tickers else {}),
            )
        except SQLAlchemyError as exc:
            self._date_stream_candidate_query_failed = True
            self.health.database_unavailable("date_stream_candidate_query", exc)
            return []
        self.health.database_recovered("date_stream_candidate_query")
        return candidates


    def _discovery_enabled(self) -> bool:
        return (
            os.getenv("DATE_STREAM_DISCOVERY_ENABLED", "true").lower() in {"true", "1", "yes", "on"}
            and callable(getattr(self.worker_manager, "discover_date_based_call", None))
        )

    def _reservation_key(self, call: dict[str, Any]) -> str:
        return STTWorkerManager._build_call_id(self.worker_manager, call)

    def _reserve_capture(self, call: dict[str, Any], settings: dict[str, int]) -> bool:
        # No await between capacity check and reservation: atomic within the
        # scheduler event loop, including bounded and background dispatch.
        key = self._reservation_key(call)
        occupied = getattr(self.worker_manager, "occupied_capture_keys", None)
        if callable(occupied):
            keys = set(occupied()) | self._capture_reservations
            count = len(keys)
            if key in keys:
                return False
        else:
            count = self._active_date_stream_captures() + len(self._capture_reservations)
            if key in self._capture_reservations:
                return False
        limit = settings.get("capture_concurrency", settings.get("concurrency", env_int("DATE_STREAM_WATCH_CONCURRENCY", 3)))
        if count >= limit:
            return False
        self._capture_reservations.add(key)
        return True

    def _capacity_snapshot(self, settings: dict[str, int]) -> dict[str, int]:
        """Describe the shared preparation/capture budget without double counting.

        A held probe and its reservation refer to one browser. Likewise, launch
        briefly leaves an active process inside its preparation task. The total
        is a union of keys, while preparation excludes held/active browsers.
        """
        active_count = self._active_date_stream_captures()
        processes = getattr(self.worker_manager, "_active_processes", {})
        active_keys = {
            key for key, process in processes.items()
            if getattr(process, "returncode", None) is None
        } if isinstance(processes, dict) else set()
        occupied = getattr(self.worker_manager, "occupied_capture_keys", None)
        if callable(occupied):
            occupied_keys = set(occupied())
            occupied_count = len(occupied_keys | self._capture_reservations)
            held_count = len(occupied_keys - active_keys)
            preparing_count = len(self._capture_reservations - occupied_keys)
        else:
            # Legacy worker doubles expose only a count, as in _reserve_capture.
            occupied_count = active_count + len(self._capture_reservations)
            held_count = 0
            preparing_count = len(self._capture_reservations)
        watch_limit = settings.get("concurrency", env_int("DATE_STREAM_WATCH_CONCURRENCY", 3))
        capture_limit = settings.get("capture_concurrency", watch_limit)
        discovery_limit = (settings.get("discovery_concurrency", env_int("DATE_STREAM_DISCOVERY_CONCURRENCY", 2))
                           if self._discovery_enabled() else watch_limit)
        discovery_count = sum(
            not task.done() and call_id not in self._preparing_call_ids
            for call_id, task in self._date_stream_background_tasks.items()
        )
        return {
            "capture_limit": capture_limit,
            "discovery_limit": discovery_limit,
            "active_discoveries": discovery_count,
            "active_captures": active_count,
            "held_captures": held_count,
            "preparing_captures": preparing_count,
            "capture_reservations": len(self._capture_reservations),
            "occupied_capture_slots": occupied_count,
            "available_capture_slots": max(0, capture_limit - occupied_count),
        }

    def _capture_environment(self, call: dict[str, Any]) -> dict[str, str]:
        capture_settings = capture_runtime_environment(
            {"WEBCAST_LIFECYCLE": "live"}
        )
        return self.worker_manager.build_isolated_capture_environment(call, capture_settings)

    async def _discard_promotable_probe(self, call: dict[str, Any]) -> None:
        discard = getattr(self.worker_manager, "discard_promotable_probe", None)
        if callable(discard):
            await discard(call)


    async def _probe_and_launch_date_stream_call(
        self,
        call: dict[str, Any],
        settings: dict[str, int],
    ) -> None:
        call_id = int(call["id"])
        ticker = str(call.get("ticker") or "UNKNOWN")
        claimed = False
        reserved = False
        watch_state: str | None = None
        outcome_recorded = False

        def record_probe_outcome(ready, error=None, *, status=None, **details):
            # A rejected handoff must not erase the browser's real failure.
            # This is a probe outcome, not a claim of live text capture success.
            nonlocal outcome_recorded
            if outcome_recorded:
                return
            outcome_recorded = True
            status = status or ('stream_ready' if ready else 'pending')
            payload = {**live_runtime.context(call), 'watch_state': watch_state,
                       'scheduled_at_utc': call.get('scheduled_at_utc'),
                       'audio_ready': bool(ready), **details}
            self.health.record_event('probe_result', status=status, error=error, **payload)
            live_runtime.record(call, 'capture', 'probe_result', status=status,
                                progress=bool(ready), error=error, **details)
        try:
            expected_date = call.get("webcast_date") or call.get("earning_at")
            schedule_identity = {}
            if expected_date is not None:
                schedule_identity = {
                    "expected_event_date": expected_date,
                    "expected_discovery_fingerprint": call.get(
                        "schedule_discovery_fingerprint"
                    ),
                }
                if call.get("schedule_revision") is not None:
                    schedule_identity["expected_schedule_revision"] = int(call["schedule_revision"])
            watch_state, probe_cooldown = probe_window(
                call,
                settings["cooldown_minutes"],
            )
            if watch_state == 'capture_retry_window_expired':
                self.health.record_event('capture_retry_window_expired', ticker=ticker,
                    call_id=call_id, status='schedule_revalidation_required',
                    scheduled_at_utc=call.get('scheduled_at_utc'),
                    action='refresh_official_schedule_before_new_capture')
                return
            claimed = self.repository.claim_stream_probe(
                call_id,
                cooldown_minutes=probe_cooldown,
                **schedule_identity,
            )
            if not claimed:
                return

            capture_session_id = STTWorkerManager.build_capture_session_id(call)
            call["_capture_session_id"] = capture_session_id
            live_runtime.prepare_attempt(call)
            self.health.record_event('probe_started', **live_runtime.context(call),
                watch_state=watch_state, scheduled_at_utc=call.get('scheduled_at_utc'),
                probe_cooldown_minutes=probe_cooldown)
            live_runtime.record(call, "capture", "attempt_started", status="discovering", progress=True,
                                watch_state=watch_state)
            runtime_env = self._capture_environment(call)
            runtime_env["STT_CAPTURE_SESSION_ID"] = capture_session_id
            timeout_key = (
                "DATE_STREAM_LOW_PRIORITY_PROBE_TIMEOUT_SECONDS"
                if watch_state
                in {"date_only_future", "date_only_stale", "scheduled", "post_event"}
                else "DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS"
            )
            runtime_env["DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS"] = os.getenv(
                timeout_key,
                (
                    "90"
                    if timeout_key == "DATE_STREAM_LOW_PRIORITY_PROBE_TIMEOUT_SECONDS"
                    else "600"
                ),
            )
            if self._discovery_enabled():
                discovery = await self.worker_manager.discover_date_based_call(call)
                needs_browser_action = discovery.get("retry_state") == "browser_action_required"
                if not discovery.get("target_identity_verified") and not needs_browser_action:
                    error = str(discovery.get("error") or "no candidate; target identity unconfirmed")
                    live_runtime.record(call, "discovery", "attempt_failed", status="pending", error=error,
                                        failure=classify_live_failure(error))
                    self._record_probe(
                        call_id, call=call, stream_ready=False, error=error,
                        watch_state=watch_state, expected_date=expected_date,
                    )
                    claimed = False
                    record_probe_outcome(False, error)
                    self.health.record_event("discovery_result", ticker=ticker, call_id=call_id,
                                             status="pending", error=error)
                    return
                if discovery.get("target_identity_verified"):
                    call["webcast_url"] = discovery["discovered_url"]
                    call["_live_discovery_proof"] = discovery["identity_proof"]
                self.health.record_event("discovery_result", ticker=ticker, call_id=call_id,
                                         status="browser_action_required" if needs_browser_action else "target_found")
                clock = validated_browser_values(call, call.get('_browser_schedule_observation'))
                if clock:
                    if browser_clock_changed(call, clock):
                        # Save before registration/audio. A new schedule version
                        # is picked up by the ordinary queue with its DB clock.
                        self._record_probe(call_id, call=call, stream_ready=False,
                            error='SCHEDULE_TIME_UPDATED browser verified the current event start',
                            watch_state=watch_state, expected_date=expected_date)
                        claimed = False
                        record_probe_outcome(False, status='deferred',
                            defer_reason='schedule_updated')
                        return
            reserved = self._reserve_capture(call, settings)
            if not reserved:
                capacity = self._capacity_snapshot(settings)
                capacity_error = (
                    "CAPACITY_WAIT target discovered; awaiting capture slot "
                    f"occupied={capacity['occupied_capture_slots']}/{capacity['capture_limit']}"
                )
                self._record_probe(
                    call_id, call=call, stream_ready=False, error=capacity_error,
                    watch_state=watch_state, expected_date=expected_date,
                )
                claimed = False
                record_probe_outcome(False, capacity_error, status='deferred',
                                     defer_reason='capacity_wait')
                self.health.record_event("capture_deferred", ticker=ticker, call_id=call_id,
                                         status="capacity_wait", **capacity)
                live_runtime.record(call, "capture", "capacity_wait", status="pending", **capacity)
                return
            self._preparing_call_ids.add(call_id)
            self.health.record_event("capture_slot", ticker=ticker, call_id=call_id,
                                     status="reserved", **self._capacity_snapshot(settings))
            ready, error = await self.worker_manager.probe_date_based_call(
                call,
                capture_env=runtime_env,
            )
            probe_policy = self._record_probe(
                call_id,
                call=call,
                stream_ready=ready,
                error=error,
                watch_state=watch_state,
                expected_date=expected_date,
            )
            claimed = False
            handoff_rejected = isinstance(probe_policy, dict) and (
                probe_policy.get('accepted') is False
                or probe_policy.get('capture_handoff_valid') is False)
            record_probe_outcome(ready, error,
                status='deferred' if ready and handoff_rejected else None,
                handoff_accepted=not handoff_rejected,
                defer_reason=('schedule_updated' if probe_policy.get('schedule_changed')
                              else 'schedule_changed_or_claimed') if handoff_rejected else None)
            if isinstance(probe_policy, dict) and (
                    probe_policy.get('accepted') is False
                    or probe_policy.get('capture_handoff_valid') is False):
                # Never promote audio opened against a superseded schedule.
                await self._discard_promotable_probe(call)
                self.health.record_event('capture_deferred' if probe_policy.get('schedule_changed') else 'capture_skipped', ticker=ticker, call_id=call_id,
                    status='schedule_updated' if probe_policy.get('schedule_changed') else 'schedule_changed_or_claimed',
                    error=error, attempt_id=call.get('_live_attempt_id'),
                    schedule_revision=call.get('schedule_revision'), audio_ready=bool(ready))
                return
            if not ready:
                # Probe errors can quote another event on an IR index. They
                # cannot authorize clearing this call's schedule or URLs.
                # Schedule reconciliation owns changes backed by official
                # event evidence; an unavailable candidate simply retries.
                if (
                    isinstance(probe_policy, dict)
                    and probe_policy.get("requires_schedule_refresh")
                ):
                    await self.schedules._refresh_schedule_after_probe_mismatch(
                        call_id,
                        ticker,
                        error,
                    )
                print(f"[DateStreamWatch] {ticker} pending: {error}")
                return

            print(f"[DateStreamWatch] {ticker} audible stream detected")
            if os.getenv("DATE_STREAM_AUTO_CAPTURE_ENABLED", "true").lower() != "true":
                await self._discard_promotable_probe(call)
                return
            if not self.repository.mark_call_running(
                call_id,
                capture_session_id=capture_session_id,
                **schedule_identity,
            ):
                self.health.record_event(
                    "capture_skipped",
                    ticker=ticker,
                    call_id=call_id,
                    status="schedule_changed_or_claimed",
                )
                print(
                    f"[DateStreamWatch] {ticker} capture skipped: "
                    "schedule changed or another worker claimed it"
                )
                await self._discard_promotable_probe(call)
                return
            try:
                live_runtime.record(call, "capture", "capture_started", status="running", progress=True)
                self.health.record_event(
                    "capture_started",
                    ticker=ticker,
                    call_id=call_id,
                    status="running",
                    watch_state=watch_state,
                    entrypoint_kind=call.get("_live_entrypoint_kind"),
                )
                await self.worker_manager.launch_date_based_audio_capture(
                    call,
                    capture_env=runtime_env,
                )
            except Exception as exc:
                await self._discard_promotable_probe(call)
                retry_scheduled = self.repository.requeue_failed_call_capture(
                    call_id,
                    error=str(exc),
                    capture_session_id=capture_session_id,
                )
                status = "retry_pending" if retry_scheduled else "failed"
                self.health.record_event(
                    "capture_failed",
                    ticker=ticker,
                    call_id=call_id,
                    status=status,
                    error=str(exc),
                )
                print(f"[DateStreamWatch] {ticker} capture launch failed: {exc}")
        except asyncio.CancelledError:
            await self._discard_promotable_probe(call)
            raise
        except SQLAlchemyError as exc:
            await self._discard_promotable_probe(call)
            self.health.database_unavailable("date_stream_probe", exc)
            record_probe_outcome(False, str(exc), status='db_unavailable')
            print(f"[DateStreamWatch] {ticker} paused: database unavailable", flush=True)
        except Exception as exc:
            await self._discard_promotable_probe(call)
            if claimed:
                try:
                    self._record_probe(
                        call_id, call=call,
                        stream_ready=False,
                        error=str(exc),
                        watch_state=watch_state,
                        expected_date=call.get("webcast_date") or call.get("earning_at"),
                    )
                except Exception:
                    pass
            record_probe_outcome(False, str(exc), status='error')
            print(f"[DateStreamWatch] {ticker} probe failed unexpectedly: {exc}")
        finally:
            if claimed and not outcome_recorded:
                record_probe_outcome(False, status='unknown',
                    defer_reason='attempt_interrupted_before_result')
            if call.get("_live_progress_dir"):
                # Dispatch has ended; capture may continue in the manager.
                # Only the capture stage can declare capture_finished.
                live_runtime.record(call, "attempt", "dispatch_finished", status="dispatched")
            self._preparing_call_ids.discard(call_id)
            if reserved:
                self._capture_reservations.discard(self._reservation_key(call))
                self.health.record_event("capture_slot", ticker=ticker, call_id=call_id,
                                         status="reservation_released", **self._capacity_snapshot(settings))
            if claimed:
                # Cancellation or DB trouble must not leave an owned probe
                # stuck until its full lease expires.
                try:
                    self._record_probe(
                        call_id, call=call, stream_ready=False, error="probe interrupted before completion",
                        watch_state=watch_state,
                        expected_date=call.get("webcast_date") or call.get("earning_at"),
                    )
                except Exception:
                    pass



    async def monitor_date_based_streams(self):
        """Run one bounded, awaited batch for maintenance and direct tests."""
        if maintenance_window_active():
            self.health.record_event("watch_cycle", status="maintenance", candidates=0)
            print("[DateStreamWatch] maintenance window active; skipping new probes")
            return 0

        settings = self._date_stream_settings()
        candidates = self._date_stream_candidates(settings)
        if self._date_stream_candidate_query_failed:
            self.health.record_event(
                "watch_cycle",
                status="db_unavailable",
                candidates=0,
                days_ahead=settings["days_ahead"],
                concurrency=settings["concurrency"],
                mode="bounded",
                **self._capacity_snapshot(settings),
            )
            return 0
        self.health.record_event(
            "watch_cycle",
            status="candidates" if candidates else "idle",
            candidates=len(candidates),
            days_ahead=settings["days_ahead"],
            concurrency=settings["concurrency"],
            mode="bounded",
            **self._capacity_snapshot(settings),
        )
        semaphore = asyncio.Semaphore(settings["discovery_concurrency"] if self._discovery_enabled()
                                      else settings["concurrency"])

        async def process(call: dict[str, Any]) -> None:
            async with semaphore:
                if (not self._discovery_enabled()
                    and self._active_date_stream_captures() >= settings["concurrency"]):
                    self.health.record_event(
                        "probe_deferred",
                        ticker=str(call.get("ticker") or "UNKNOWN"),
                        call_id=call.get("id"),
                        status="capture_capacity_reached",
                        concurrency=settings["concurrency"],
                        **self._capacity_snapshot(settings),
                    )
                    return
                await self._probe_and_launch_date_stream_call(call, settings)

        await asyncio.gather(*(process(call) for call in candidates))
        return len(candidates)


    async def dispatch_date_based_streams(self):
        """Dispatch new probes promptly without blocking the next minute's tick."""
        if maintenance_window_active():
            self.health.record_event("watch_cycle", status="maintenance", candidates=0)
            return 0
        if self._date_stream_dispatch_lock is None:
            self._date_stream_dispatch_lock = asyncio.Lock()

        async with self._date_stream_dispatch_lock:
            for call_id, task in tuple(self._date_stream_background_tasks.items()):
                if task.done():
                    self._date_stream_background_tasks.pop(call_id, None)

            settings = self._date_stream_settings()
            candidates = self._date_stream_candidates(settings)
            active_probe_count = len(self._date_stream_background_tasks)
            active_capture_count = self._active_date_stream_captures()
            active_count = active_probe_count + active_capture_count
            if self._date_stream_candidate_query_failed:
                self.health.record_event(
                    "watch_cycle",
                    status="db_unavailable",
                    candidates=0,
                    dispatched=0,
                    active_probes=active_probe_count,
                    days_ahead=settings["days_ahead"],
                    concurrency=settings["concurrency"],
                    mode="background",
                    **self._capacity_snapshot(settings),
                )
                return 0
            if self._discovery_enabled():
                # Preparing/recording calls have their own reservation budget.
                # They must not occupy lightweight discovery slots as well.
                discovery_count = sum(
                    not task.done() and call_id not in getattr(self, "_preparing_call_ids", set())
                    for call_id, task in self._date_stream_background_tasks.items()
                )
                available_slots = max(0, settings["discovery_concurrency"] - discovery_count)
            else:
                available_slots = max(0, settings["concurrency"] - active_count)
            selected: list[dict[str, Any]] = []
            if available_slots:
                for call in candidates:
                    call_id = int(call["id"])
                    if call_id in self._date_stream_background_tasks:
                        continue
                    selected.append(call)
                    if len(selected) >= available_slots:
                        break

            self.health.record_event(
                "watch_cycle",
                status="dispatched" if selected else ("busy" if candidates else "idle"),
                candidates=len(candidates),
                dispatched=len(selected),
                active_probes=active_probe_count,
                days_ahead=settings["days_ahead"],
                concurrency=settings["concurrency"],
                mode="background",
                **self._capacity_snapshot(settings),
            )
            for call in selected:
                call_id = int(call["id"])
                task = asyncio.create_task(
                    self._probe_and_launch_date_stream_call(call, settings),
                    name=f"date-stream-probe-{call_id}",
                )
                self._date_stream_background_tasks[call_id] = task

                def release_task(
                    completed: asyncio.Task[Any],
                    *,
                    tracked_call_id: int = call_id,
                ) -> None:
                    if self._date_stream_background_tasks.get(tracked_call_id) is completed:
                        self._date_stream_background_tasks.pop(tracked_call_id, None)

                task.add_done_callback(release_task)
            return len(selected)
