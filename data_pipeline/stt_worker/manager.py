from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import signal
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..collectors.schedules.event_routes import normalize_route, read_route_proof, period_mismatch, stored_event_kind_conflict
from ..collectors.schedules.browser_observation import validated_browser_values, browser_clock_changed
from ..failure_reasons import classify_stream_failure, classify_live_failure
from .. import live_runtime
from ..live_telemetry import read_progress_snapshot


@dataclass(frozen=True)
class WebcastProbeResult:
    audible: bool
    error: str | None
    output: str
    return_code: int | None
    runtime_environment: dict[str, str] | None = None


@dataclass
class _PromotableProbeProcess:
    """A proven browser/audio process held briefly for in-place STT promotion."""

    process: asyncio.subprocess.Process
    output_task: asyncio.Task[None]
    output_tail: deque[str]
    runtime_environment: dict[str, str]
    promote_file: str
    abort_file: str


class STTWorkerManager:
    def __init__(self) -> None:
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._promotable_probes: dict[str, _PromotableProbeProcess] = {}
        self._entrypoint_retry_not_before: dict[str, float] = {}
        self._discovery_cache: dict[str, tuple[float, tuple, dict[str, Any]]] = {}

    def active_capture_count(self) -> int:
        """Return live browser/STT captures that currently consume a worker slot."""
        return sum(
            process.returncode is None
            for process in self._active_processes.values()
        )

    def occupied_capture_keys(self) -> set[str]:
        """One key per held/preparing-complete/running browser, never double count."""
        return {
            key for key, process in self._active_processes.items()
            if process.returncode is None
        } | {
            key for key, held in self._promotable_probes.items()
            if held.process.returncode is None
        }

    async def discover_date_based_call(self, call: dict[str, Any]) -> dict[str, Any]:
        """Revalidate official event pages and IR routes, preserving partial evidence."""
        live_runtime.prepare_attempt(call)
        fingerprint = (self._target_event_date(call), str(call.get('schedule_revision') or 0),
                       str(call.get('schedule_discovery_fingerprint') or ''),
                       str(call.get('event_url') or ''), str(call.get('webcast_url') or ''),
                       str(call.get('schedule_discovery_checked_at') or call.get('time_verified_at') or ''),
                       self._target_event_time(call), live_runtime.operator_route(call))
        key, now = self._build_call_id(call), time.monotonic()
        for cached_key, entry in tuple(self._discovery_cache.items()):
            if entry[0] <= now:
                self._discovery_cache.pop(cached_key, None)
        cached = self._discovery_cache.get(key)
        if (cached and cached[1] == fingerprint
                and self._fresh_discovery_proof(call, cached[2].get('discovered_url', ''), cached[2].get('identity_proof'))):
            live_runtime.record(call, 'discovery', 'cache_hit', status='target_found', progress=True)
            return dict(cached[2])
        stored = self._stored_target_proof(call) or self._remembered_target_proof(call)
        blocked_targets = live_runtime.remembered(call, {'auth_required', 'access_blocked', 'identity_mismatch', 'replay_source'})
        if stored and stored['target_url'] not in blocked_targets:
            live_runtime.record(call, 'discovery', 'official_route_reused', status='target_found', progress=True,
                                target_url=stored['target_url'])
            return {'target_identity_verified': True, 'discovered_url': stored['target_url'], 'identity_proof': stored}
        issuer = str(call.get('ir_url') or '')
        if not issuer:
            return {'target_identity_verified': False, 'error': 'no candidate: missing IR URL'}
        issuer_host = urlparse(issuer).hostname
        routes = []
        # An operator hint is an unverified same-issuer page, never a proof.
        for route in (live_runtime.operator_route(call), call.get('event_url'), issuer):
            route = str(route or '')
            if (route and normalize_route(issuer, route) == route
                    and urlparse(route).hostname == issuer_host and route not in routes):
                routes.append(route)
        errors = []
        total_deadline = time.monotonic() + max(10., float(os.getenv('DATE_STREAM_DISCOVERY_TOTAL_TIMEOUT_SECONDS', '90')))
        for index, route in enumerate(routes):
            blocked = live_runtime.remembered(call, {'auth_required', 'access_blocked'})
            if route in blocked:
                errors.append('ENTRYPOINT_COOLDOWN_ACTIVE protected official route')
                continue
            remaining = total_deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(max(5., float(os.getenv('DATE_STREAM_DISCOVERY_TIMEOUT_SECONDS', '45'))), remaining)
            environment = {**live_runtime.prepare_attempt(call),
                'WEBCAST_LIFECYCLE': 'live', 'WEBCAST_DISCOVERY_ONLY': 'true',
                'WEBCAST_DIRECT_TARGET_URL': '', 'WEBCAST_LIVE_IDENTITY_PROOF': '',
                'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'false', 'WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION': 'true',
                'WEBCAST_ALLOW_REGISTRATION_SUBMISSION': 'false', 'WEBCAST_VISION_ENABLED': 'false',
                'WEBCAST_TARGET_DATE': self._target_event_date(call),
                'WEBCAST_TARGET_YEAR': str(call.get('verified_fiscal_year') or ''),
                'WEBCAST_TARGET_QUARTER': str(call.get('verified_fiscal_quarter') or ''),
                'WEBCAST_TARGET_TIME_UTC': self._target_event_time(call),
                'WEBCAST_LIVE_EXCLUDED_URLS': ','.join(live_runtime.remembered(call, {'identity_mismatch', 'replay_source'})),
                'WEBCAST_LEARNING_ENABLED': 'false', 'WEBCAST_HOLD_SECONDS': '0'}
            command = ['python', '-m', 'data_pipeline.collectors.streams.browser_webcast',
                       '--ticker', str(call['ticker']).upper(), '--ir-url', route, '--discovery-only', '--json']
            if os.getenv('DATE_STREAM_DISCOVERY_HEADED', os.getenv('WEBCAST_HEADED', 'true')).lower() in {'true','1','yes','on'}:
                command = ['xvfb-run', '-a', *command, '--headed']
            if os.getenv('WEBCAST_CAPTURE_RUNNER', 'docker').lower() == 'container':
                process_env = {**os.environ, **environment}
            else:
                compose = Path(__file__).resolve().parents[2] / 'infra/docker-compose.yml'
                prefix = ['docker','compose','-f',str(compose),'--profile','tools','run','--rm','--no-deps']
                for name, value in environment.items():
                    prefix.extend(['-e', f'{name}={value}'])
                command = [*prefix, 'browser-webcast', *command]
                process_env = {**os.environ, 'COMPOSE_IGNORE_ORPHANS': '1'}
            live_runtime.record(call, 'discovery', 'route_started', status='running', progress=True,
                                route_url=route, route_index=index, timeout_seconds=timeout)
            process = output_task = None
            tail: deque[bytes] = deque(maxlen=256)
            try:
                process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT, env=process_env, start_new_session=True)
                async def collect_output():
                    partial = b''
                    while True:
                        chunk = await process.stdout.read(4096)
                        if not chunk:
                            break
                        tail.append(chunk)
                        partial += chunk
                        while b'\n' in partial:
                            line, partial = partial.split(b'\n', 1)
                            live_runtime.record(call, 'discovery', 'child_output', line=line.decode(errors='replace')[:8000])
                        if len(partial) > 16384:
                            partial = b''
                    if partial:
                        live_runtime.record(call, 'discovery', 'child_output', line=partial.decode(errors='replace')[:8000])
                    await process.wait()
                    return b''.join(tail), None
                output_task = asyncio.create_task(collect_output())
                output, _ = await asyncio.wait_for(asyncio.shield(output_task), timeout=timeout)
            except asyncio.CancelledError:
                if process is not None and output_task is not None:
                    await self._terminate_probe_process(process, output_task)
                raise
            except TimeoutError:
                if process is not None and output_task is not None:
                    await self._terminate_probe_process(process, output_task)
                error = 'DISCOVERY_TIMEOUT no final result before official route deadline'
                live_runtime.record(call, 'discovery', 'route_failed', status='timeout', error_code='DISCOVERY_TIMEOUT',
                                    route_url=route, partial_output_bytes=sum(map(len, tail)))
                errors.append(error)
                continue
            except Exception as exc:
                if process is not None and output_task is not None:
                    await self._terminate_probe_process(process, output_task)
                errors.append(f'DISCOVERY_FAILED {type(exc).__name__}: {exc}')
                continue
            text_output = (output or b'').decode(errors='replace')
            payload = None
            for line in text_output.splitlines():
                if line.startswith('WEBCAST_DISCOVERY_RESULT='):
                    with contextlib.suppress(ValueError, TypeError):
                        payload = json.loads(line.split('=', 1)[1])
            if isinstance(payload, dict) and 'schedule_observation' in payload:
                observation = payload.get('schedule_observation')
                observation_proof = (observation or {}).get('identity_proof') if isinstance(observation, dict) else None
                self._retain_browser_observation(call, observation,
                    identity_verified=bool(self._bound_route_proof(call, observation_proof)),
                    route_url=route)
            if not isinstance(payload, dict):
                error = self._process_error(text_output, process.returncode, operation='link discovery') or 'DISCOVERY_NO_RESULT'
            elif payload.get('retry_state') == 'browser_action_required':
                return {'target_identity_verified': False, 'retry_state': 'browser_action_required',
                        'error': 'DISCOVERY_REQUIRES_BROWSER_ACTION'}
            else:
                proof = payload.get('event_identity') or payload.get('identity_proof') or {}
                url = str(payload.get('discovered_url') or '')
                if payload.get('target_identity_verified') and self._fresh_discovery_proof(call, url, proof):
                    proof = self._remember_target_proof(call, proof)
                    result = {'target_identity_verified': True, 'discovered_url': url, 'identity_proof': proof}
                    self._discovery_cache[key] = (time.monotonic()+90, fingerprint, result)
                    live_runtime.record(call, 'discovery', 'target_verified', status='target_found', progress=True,
                                        target_url=url, route_url=route)
                    return result
                error = str(payload.get('error') or 'LIVE_TARGET_UNCONFIRMED no dated target candidate')
            self._cooldown_failed_entrypoint(call, 'discovery', route, error)
            live_runtime.record(call, 'discovery', 'route_failed', status='pending', route_url=route,
                                error=error, failure=classify_live_failure(error))
            errors.append(error)
        error = ' | '.join(errors[-3:]) or 'DISCOVERY_TIMEOUT no route completed'
        return {'target_identity_verified': False, 'error': error[:1000],
                'error_code': classify_live_failure(error)['error_code']}

    @staticmethod
    def _stored_target_proof(call: dict[str, Any]) -> dict[str, Any] | None:
        """Reuse fresh, date-linked official routes even when IR navigation fails."""
        if not str(call.get("schedule_source") or "").lower().startswith("official"):
            return None
        if str(call.get("schedule_revalidation_status") or "clear") != "clear":
            # A verified event route can remain usable when only its exact
            # start clock conflicts. Legacy ambiguous_call_time also described
            # event-date conflicts, so require the new explicit classification.
            try:
                detail = call.get("schedule_revalidation_evidence") or {}
                if isinstance(detail, str):
                    detail = json.loads(detail)
            except (ValueError, TypeError):
                return None
            if not (
                call.get("schedule_revalidation_status") == "provisional_watch"
                and call.get("schedule_revalidation_reason") == "ambiguous_call_time"
                and isinstance(detail, dict)
                and detail.get("conflict_kind") == "start_time_conflict"
                and detail.get("route_identity_verified") is True
            ):
                return None
        if not call.get("schedule_discovery_fingerprint"):
            return None
        checked = call.get("schedule_discovery_checked_at") or call.get("time_verified_at")
        try:
            observed = checked if isinstance(checked, datetime) else datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 21600:
                return None
        except (TypeError, ValueError):
            return None
        target_date = STTWorkerManager._target_event_date(call)
        evidence = str(call.get("schedule_evidence") or "")
        route = read_route_proof(evidence)
        if stored_event_kind_conflict(evidence):
            return None
        if route and route.get('source_observed_at') is not None:
            try:
                source_observed = datetime.fromisoformat(str(route['source_observed_at']).replace('Z', '+00:00'))
                if (source_observed.tzinfo is None
                        or not 0 <= (datetime.now(timezone.utc) - source_observed).total_seconds() <= 21600):
                    return None
                observed = min(observed, source_observed)
            except (TypeError, ValueError):
                return None
        issuer = str(call.get("_issuer_ir_url") or call.get("ir_url") or "")
        issuer_host = (urlparse(issuer).hostname or "").lower().removeprefix("www.")
        proof_host = (urlparse(str((route or {}).get("issuer_url") or "")).hostname or "").lower().removeprefix("www.")
        if not (route and route.get("relation") == "same_event_container"
                and route.get("event_type") == "earnings_call"
                and route.get("date") == target_date
                and str(route.get("ticker") or "").upper() == str(call.get("ticker") or "").upper()
                and issuer_host and (proof_host == issuer_host or proof_host.endswith("." + issuer_host))):
            return None
        for field, proof_field in (("verified_fiscal_year", "fiscal_year"),
                                   ("verified_fiscal_quarter", "fiscal_quarter")):
            if call.get(field) and str(route.get(proof_field) or "").upper() != str(call[field]).upper():
                return None
        for kind in ("webcast_url", "event_url"):
            url = str(call.get(kind) or "")
            if target_date and route.get(kind) == url and normalize_route(issuer, url) == url:
                return {"verified": True, "call_id": call.get("id"), "schedule_revision": int(call.get("schedule_revision") or 0),
                        "call_ticker": str(call["ticker"]).upper(),
                        "target_date": target_date, "source_url": issuer,
                        "target_url": url, "observed_at": datetime.now(timezone.utc).isoformat(),
                        "source_observed_at": observed.isoformat(), "evidence": evidence[:1800]}
        return None

    @staticmethod
    def _known_non_earnings_routes(call: dict[str, Any]) -> set[str]:
        """Bind negative event evidence to its original typed URLs, not new ones.

        Discovery may replace call.webcast_url while the DB's old evidence is
        still present. Never transfer that contradiction to the replacement.
        The issuer index remains available for discovering another event.
        """
        evidence = str(call.get("schedule_evidence") or "")
        if not stored_event_kind_conflict(evidence):
            return set()
        route = read_route_proof(evidence)
        issuer = str(call.get("_issuer_ir_url") or call.get("ir_url") or "")
        if (not route or route.get("date") != STTWorkerManager._target_event_date(call)
                or str(route.get("ticker") or "").upper() != str(call.get("ticker") or "").upper()):
            return set()
        try:
            owner = (urlparse(issuer).hostname or "").lower().removeprefix("www.")
            source = (urlparse(str(route.get("issuer_url") or "")).hostname or "").lower().removeprefix("www.")
        except ValueError:
            return set()
        if not owner or not (source == owner or source.endswith("." + owner)):
            return set()
        for field, proof_field in (("verified_fiscal_year", "fiscal_year"),
                                   ("verified_fiscal_quarter", "fiscal_quarter")):
            if (call.get(field) and route.get(proof_field)
                    and str(call[field]).upper() != str(route[proof_field]).upper()):
                return set()
        return {str(route[kind]) for kind in ("webcast_url", "event_url")
                if route.get(kind) and str(route[kind]).rstrip("/") != issuer.rstrip("/")
                and normalize_route(issuer, route[kind]) == route[kind]}

    @staticmethod
    def _fresh_discovery_proof(call: dict[str, Any], url: str, proof: Any, *, max_age=120) -> bool:
        if not isinstance(proof, dict) or proof.get("verified") is not True:
            return False
        if url in STTWorkerManager._known_non_earnings_routes(call):
            return False
        issuer = str(call.get("_issuer_ir_url") or call.get("ir_url") or "")
        try:
            source, owner, target = urlparse(str(proof.get('source_url') or '')), urlparse(issuer), urlparse(url)
            if (normalize_route(issuer, url) != url or proof.get("target_url") != url
                    or source.scheme not in {'http', 'https'} or not owner.hostname
                    or source.hostname != owner.hostname or source.username or source.password
                    or source.port == 0 or target.port == 0):
                return False
        except (TypeError, ValueError):
            return False
        if proof.get("target_date") != STTWorkerManager._target_event_date(call):
            return False
        if str(proof.get("call_ticker") or "").upper() != str(call.get("ticker") or "").upper():
            return False
        for field, expected in (('call_id', call.get('id')), ('schedule_revision', int(call.get('schedule_revision') or 0))):
            if field in proof and str(proof[field]) != str(expected):
                return False
        if (not proof.get("evidence") or period_mismatch(call, str(proof['evidence']))
                or stored_event_kind_conflict(proof["evidence"])):
            return False
        from ..collectors.streams.browser.navigation import provider_event_id
        if proof.get('provider_event_id') and proof['provider_event_id'] != provider_event_id(url):
            return False
        try:
            observed = datetime.fromisoformat(str(proof.get("observed_at")).replace("Z", "+00:00"))
            source_observed = datetime.fromisoformat(str(proof.get('source_observed_at') or proof['observed_at']).replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            return (0 <= (now - observed).total_seconds() <= max_age
                    and 0 <= (now - source_observed).total_seconds() <= 21600)
        except (TypeError, ValueError):
            return False

    @classmethod
    def _bound_route_proof(cls, call, proof):
        """Bind authenticated child evidence, never an arbitrary stored URL."""
        if not isinstance(proof, dict) or not cls._fresh_discovery_proof(
                call, str(proof.get('target_url') or ''), proof, max_age=21600):
            return None
        from ..collectors.streams.browser.navigation import provider_event_id
        return {**proof, 'call_id': call.get('id'),
                'schedule_revision': int(call.get('schedule_revision') or 0),
                'provider_event_id': provider_event_id(proof['target_url'])}

    @classmethod
    def _remember_target_proof(cls, call, proof):
        bound = cls._bound_route_proof(call, proof)
        if bound:
            live_runtime.remember_verified_route(call, bound)
        return bound

    @classmethod
    def _remembered_target_proof(cls, call):
        proof = live_runtime.remembered_verified_route(call)
        # Persistent evidence must explicitly name the call and revision; the
        # older unbound discovery payload is accepted only from a current child.
        if not isinstance(proof, dict) or not all(key in proof for key in ('call_id', 'schedule_revision')):
            return None
        proof = cls._bound_route_proof(call, proof)
        if not proof:
            return None
        return {**proof, 'source_observed_at': proof.get('source_observed_at') or proof['observed_at'],
                'observed_at': datetime.now(timezone.utc).isoformat()}

    @classmethod
    def _retain_browser_observation(cls, call, observation, *, identity_verified, route_url, event=None):
        """Carry authenticated source readings to the common clock writer.

        A later failed route cannot erase an earlier reading. A conflicting
        verified reading must reach DB reconciliation, not be discarded here.
        """
        from ..collectors.streams.browser.navigation import same_event_route
        from ..collectors.schedules.browser_observation import proof_extends_route
        from ..collectors.schedules.clock_reconciliation import instant, source_key, normalize_observations
        previous = call.get('_browser_schedule_observation')
        previous_values = validated_browser_values(call, previous)
        values = validated_browser_values(call, observation) if identity_verified else None
        if not values:
            if previous is not None and not previous_values:
                call.pop('_browser_schedule_observation', None)
            # An explicitly ambiguous page with no validated alternative cannot
            # authorize reusing its old preferred clock. Unknown/foreign failed
            # routes otherwise leave valid evidence intact.
            if (previous_values and identity_verified and observation is None
                    and event == 'browser_start_ambiguous'
                    and same_event_route(previous['identity_proof']['target_url'], route_url)):
                call.pop('_browser_schedule_observation', None)
                call['_browser_schedule_conflict'] = True
                live_runtime.record(call, 'schedule', 'browser_clock_conflict', status='unverified', route_url=route_url)
            elif previous_values:
                live_runtime.record(call, 'schedule', 'browser_clock_retained', status='verified',
                                    route_url=route_url, retained_source_url=previous.get('evidence_url'))
            return
        proof = cls._bound_route_proof(call, observation.get('identity_proof'))
        if not proof:
            return
        incoming = {**observation, 'identity_proof': proof,
                    'call_id': call.get('id'), 'schedule_revision': int(call.get('schedule_revision') or 0)}
        sources = [incoming]
        if isinstance(previous, dict) and isinstance(previous.get('identity_proof'), dict):
            old_proof = previous['identity_proof']
            if (same_event_route(str(old_proof.get('target_url') or ''), proof['target_url'])
                    or proof_extends_route(old_proof, proof, now=datetime.now(timezone.utc))):
                sources.insert(0, previous)
        readings = {}
        for source in sources:
            nested = source.get('clock_observations')
            for reading in [*(nested if isinstance(nested, list) else []), source]:
                if not isinstance(reading, dict):
                    continue
                raw = {key: value for key, value in reading.items() if key != 'clock_observations'}
                key, observed = source_key(raw.get('evidence_url')), instant(raw.get('observed_at'))
                if not key or observed is None:
                    continue
                current = readings.get(key, [])
                old_time = instant(current[0]['observed_at']) if current else None
                if old_time is None or observed > old_time:
                    readings[key] = [raw]
                elif observed == old_time and all(item.get('scheduled_at_utc') != raw.get('scheduled_at_utc') for item in current):
                    # Equal-time contradictory readings must reach consensus as
                    # a conflict, not be resolved by Python dictionary order.
                    current.append(raw)
        chosen = (previous if previous_values and values['observed_at'] < previous_values['observed_at']
                  and same_event_route(previous['identity_proof']['target_url'], proof['target_url']) else incoming)
        candidate = {**chosen, 'clock_observations': [item for group in readings.values() for item in group]}
        merged_values = validated_browser_values(call, candidate)
        if merged_values is None:
            # Even previously accepted sources need a valid relation to the
            # chosen route. Reject invalid historical evidence without losing
            # a valid new observation or disabling the validator.
            candidate = incoming
            merged_values = validated_browser_values(call, candidate)
            if merged_values is None:
                return
        facts = normalize_observations(merged_values['clock_observations'])
        conflicted = (len({row['value'] for row in facts.values()}) > 1
                      or any(row.get('conflicting_values') for row in facts.values()))
        call['_browser_schedule_observation'] = candidate
        call['_browser_schedule_conflict'] = conflicted
        if conflicted:
            live_runtime.record(call, 'schedule', 'browser_clock_conflict', status='pending_reconciliation',
                                route_url=route_url, clock_source_count=len(facts))
        cls._remember_target_proof(call, candidate['identity_proof'])

    @staticmethod
    def _probe_timeout_seconds(explicit_timeout: float | None = None) -> float:
        """Keep the outer supervisor alive through playback and audio fallbacks."""
        if explicit_timeout is not None:
            return max(1.0, float(explicit_timeout))
        configured = float(os.getenv("DATE_STREAM_PROBE_TIMEOUT_SECONDS", "540"))
        playback_wait = max(
            1.0,
            float(os.getenv("WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS", "180")),
        )
        warmup = max(
            0.0,
            float(os.getenv("WEBCAST_AUDIO_WARMUP_SECONDS", "12")),
        )
        audio_wait = max(
            1.0,
            float(os.getenv("DATE_STREAM_AUDIO_WAIT_SECONDS", "90")),
        )
        # The shell performs the normal probe, a direct-media fallback, and a
        # YouTube fallback. Leave a small allowance for navigation and cleanup.
        required = playback_wait + warmup + (audio_wait * 3) + 60.0
        return max(configured, required)

    @staticmethod
    def _cleanup_grace_seconds(requested: float | str | None = None) -> float:
        """Allow the shell's bounded PCM/browser teardown before force-killing.

        PCM drain can use seven seconds and Chromium reaping five, before
        source watchers/fallbacks and private PulseAudio cleanup. The old
        five/ten-second parent deadlines could interrupt that normal sequence.
        Existing overrides may extend this shared minimum, never shorten it.
        """
        values = [30.0]
        for value in (os.getenv("WEBCAST_CLEANUP_GRACE_SECONDS", "30"), requested):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                values.append(parsed)
        return max(values)

    @staticmethod
    async def _terminate_probe_process(
        process: asyncio.subprocess.Process,
        communicate_task: asyncio.Task[Any],
    ) -> tuple[bytes | None, bytes | None]:
        """Stop a probe gracefully so its shell trap can reap Chromium and Xvfb."""
        grace_seconds = STTWorkerManager._cleanup_grace_seconds(
            os.getenv("DATE_STREAM_PROBE_TERMINATE_GRACE_SECONDS", "30"),
        )
        kill_grace_seconds = max(
            1.0,
            float(os.getenv("DATE_STREAM_PROBE_KILL_GRACE_SECONDS", "5")),
        )
        try:
            process.terminate()
        except (AttributeError, ProcessLookupError):
            pass
        try:
            return await asyncio.wait_for(
                asyncio.shield(communicate_task),
                timeout=grace_seconds,
            )
        except TimeoutError:
            pass

        pid = getattr(process, "pid", None)
        try:
            if pid:
                os.killpg(int(pid), signal.SIGKILL)
            else:
                process.kill()
        except (AttributeError, ProcessLookupError, PermissionError):
            with contextlib.suppress(AttributeError, ProcessLookupError):
                process.kill()
        try:
            return await asyncio.wait_for(
                asyncio.shield(communicate_task),
                timeout=kill_grace_seconds,
            )
        except TimeoutError:
            communicate_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communicate_task
            return b"", None

    @staticmethod
    def _probe_failure_stage(output: str) -> str:
        value = str(output or "")
        if re.search(r"NOT_LIVE_YET|not yet available|has not started", value, re.I):
            return "lifecycle"
        if re.search(
            r"CANDIDATE_NAVIGATION_FAILED|webcast target opened:\s*about:blank|"
            r"direct replay candidate navigation (?:warning|timed out)",
            value,
            re.I,
        ):
            return "candidate_navigation"
        if re.search(r"REGISTRATION_(?:BLOCKED|REQUIRED)|registration form", value, re.I):
            return "registration"
        if re.search(
            r"PLAYBACK_READY_TIMED_OUT|no active media|player control search timed out|"
            r"playback was not detected",
            value,
            re.I,
        ):
            return "player_activation"
        if re.search(r"AUDIO_NOT_DETECTED|PulseAudio monitor", value, re.I):
            return "audio"
        return "discovery"

    def build_isolated_capture_environment(
        self,
        call: dict[str, Any],
        capture_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build per-call browser/audio paths so concurrent jobs do not share temp files."""
        return self._probe_runtime_environment(call, capture_env)

    @staticmethod
    def host_runtime_artifact_path(path_value: str) -> Path:
        """Map a container-mounted /app artifact back to the host repository."""
        if path_value.startswith("/app/"):
            repository_root = Path(__file__).resolve().parents[2]
            return repository_root / path_value.removeprefix("/app/")
        return Path(path_value)

    async def launch_mission(self, call):
        call = dict(call)
        ticker = str(call["ticker"]).upper()
        process_key = self._build_call_id(call)
        capture_session_id = str(
            call.get("_capture_session_id") or self.build_capture_session_id(call)
        )[:128]
        call["_capture_session_id"] = capture_session_id
        existing = self._active_processes.get(process_key)
        if existing and existing.returncode is None:
            print(f"[STTWorker] {ticker} already running call_id={process_key}")
            return

        await self._resolve_webcast_source(call)
        # The subprocess writes segments under the unique capture session.  A
        # previous mission's text can therefore never prove this run complete.
        command = self._build_command(call, capture_session_id)
        print(f"[STTWorker] launching {ticker} call_id={process_key}")
        process = await asyncio.create_subprocess_exec(*command)
        self._active_processes[process_key] = process
        asyncio.create_task(self._watch_process(call, process_key, process))

    async def probe_date_based_call(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """Probe live candidates with the shared browser engine until one is audible.

        Pre-resolved webcast and event URLs run first. When one is stale or not
        live, the worker falls back to the issuer IR page and keeps using the
        same shared discovery and playback flow. A provider target that opens
        but mismatches the call is excluded on the next pass.
        """
        base_environment = {
            "WEBCAST_LIFECYCLE": "live",
            **(capture_env or {}),
        }
        promotion_enabled = bool(base_environment.get("STT_CAPTURE_SESSION_ID")) and (
            str(
                base_environment.get(
                    "WEBCAST_PROBE_PROMOTION_ENABLED",
                    os.getenv("WEBCAST_PROBE_PROMOTION_ENABLED", "true"),
                )
            ).lower()
            in {"1", "true", "yes", "on"}
        )
        base_environment["WEBCAST_PROBE_PROMOTION_ENABLED"] = (
            "true" if promotion_enabled else "false"
        )
        await self.discard_promotable_probe(call)
        entrypoints = self._live_entrypoints(call)
        if not entrypoints:
            return False, "missing IR URL"

        configured_attempts = max(
            1,
            int(os.getenv("DATE_STREAM_CANDIDATE_ATTEMPTS", "3")),
        )
        # Every distinct stored route gets one attempt before a failed route is
        # retried. This prevents a noisy webcast URL from starving event_url or
        # the issuer IR fallback when the configured budget is small.
        max_attempts = max(configured_attempts, len(entrypoints))
        retry_delay = max(
            0.0,
            float(os.getenv("DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS", "1")),
        )
        loop = asyncio.get_running_loop()
        probe_deadline = loop.time() + max(
            30.0,
            float(
                base_environment.get(
                    "DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS",
                    os.getenv("DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS", "600"),
                )
            ),
        )
        now = time.monotonic()
        remembered_cooldowns = live_runtime.remembered(call, {"auth_required", "access_blocked", "replay_source"})
        pending = [
            entrypoint
            for entrypoint in entrypoints
            if self._entrypoint_retry_not_before.get(
                self._entrypoint_cooldown_key(call, *entrypoint),
                0.0,
            )
            <= now and entrypoint[1] not in remembered_cooldowns
        ]
        if not pending:
            remaining = min(
                max(
                    0.0,
                    self._entrypoint_retry_not_before.get(
                        self._entrypoint_cooldown_key(call, *entrypoint),
                        now,
                    )
                    - now,
                    float(remembered_cooldowns.get(entrypoint[1], {}).get('expires_at') or 0) - time.time(),
                )
                for entrypoint in entrypoints
            )
            return (
                False,
                f"ENTRYPOINT_COOLDOWN_ACTIVE retry_after_seconds={int(remaining) + 1}",
            )
        excluded_targets: set[str] = set(live_runtime.remembered(call, {"identity_mismatch", "replay_source"}))
        errors: list[str] = []
        attempts = 0

        while pending and attempts < max_attempts:
            entrypoint_kind, entrypoint_url = pending.pop(0)
            attempts += 1
            probe_call = {
                **call,
                "ir_url": entrypoint_url,
                "_issuer_ir_url": call.get("ir_url"),
                "_live_entrypoint_kind": entrypoint_kind,
                "_live_entrypoint_url": entrypoint_url,
                "_live_route_attempt": attempts,
            }
            attempt_environment = dict(base_environment)
            attempt_environment["WEBCAST_LIVE_EXCLUDED_URLS"] = ",".join(
                sorted(excluded_targets)
            )
            print(
                f"[STTWorker] live candidate probe {call.get('ticker')} "
                f"attempt={attempts}/{max_attempts} entrypoint={entrypoint_kind}",
                flush=True,
            )
            heartbeat_task = asyncio.create_task(
                self._probe_heartbeat_loop(probe_call.get("id"))
            )
            try:
                remaining_seconds = probe_deadline - loop.time()
                if remaining_seconds <= 0:
                    errors.append("probe call budget exhausted")
                    break
                result = await self.probe_webcast_url_detailed(
                    probe_call,
                    capture_env=attempt_environment,
                    timeout_seconds=min(
                        self._probe_timeout_seconds(),
                        remaining_seconds / max(1, len(pending) + 1),
                        max(30., float(os.getenv("DATE_STREAM_ROUTE_PROBE_MAX_SECONDS", "240"))),
                    ),
                )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            result_error = result.error or "no audible output"
            live_runtime.record(call, "capture", "route_probe_result", status="audio_ready" if result.audible else "pending",
                                progress=result.audible, route_url=entrypoint_url, route_index=attempts, error=result.error,
                                failure=classify_live_failure(result.error) if result.error else None)
            identity_verified = self._probe_target_identity_verified(
                result.runtime_environment or attempt_environment
            )
            replay = self._verified_replay_source(call, result.runtime_environment or attempt_environment)
            if replay:
                await self.discard_promotable_probe(call)
                target = replay['source_target_url']
                self._remember_replay_source(call, replay)
                excluded_targets.add(target)
                pending = [item for item in pending if item[1] != target]
                errors.append('VERIFIED_REPLAY_SOURCE recording excluded; rediscover current event')
                continue
            if call.get('_live_progress_dir'):
                clock_snapshot = read_progress_snapshot(call['_live_progress_dir']).get('schedule') or {}
                if (str(clock_snapshot.get('schedule_revision')) == str(call.get('schedule_revision') or 0)
                        and str(clock_snapshot.get('attempt_id')) == str(call.get('_live_attempt_id'))
                        and str(clock_snapshot.get('call_id')) == str(call.get('id'))
                        and 'observation' in clock_snapshot):
                    self._retain_browser_observation(call, clock_snapshot.get('observation'),
                        identity_verified=identity_verified, route_url=entrypoint_url,
                        event=clock_snapshot.get('event'))
            require_identity = (
                (result.runtime_environment or attempt_environment).get(
                    "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION",
                    os.getenv("WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION", "true"),
                ).lower()
                in {"1", "true", "yes", "on"}
            )
            if result.audible and require_identity and not identity_verified:
                result_error = (
                    "TARGET_IDENTITY_UNCONFIRMED audible media was rejected before capture"
                )
                await self.discard_promotable_probe(call)

            if result.audible and (identity_verified or not require_identity):
                # The long-running capture must start from the same entrypoint
                # that produced the successful probe, otherwise it may reopen
                # a generic IR page and select a different event.
                call["_live_entrypoint_url"] = entrypoint_url
                call["_live_entrypoint_kind"] = entrypoint_kind
                call["_live_excluded_urls"] = sorted(excluded_targets)
                # An alternate event/webcast entrypoint has a different
                # artifact prefix. Carry the exact winning environment into
                # capture so its final player URL, media candidates, recipe,
                # and storage state are not replaced by the original IR page.
                winning_environment = dict(
                    result.runtime_environment or attempt_environment
                )
                if identity_verified or not require_identity:
                    winning_environment["WEBCAST_LIVE_ENTRYPOINT_VERIFIED"] = "true"
                winning_environment["WEBCAST_LIVE_EXCLUDED_URLS"] = ",".join(
                    sorted(excluded_targets)
                )
                manifest_path = self._write_capture_manifest(
                    call,
                    winning_environment,
                    result,
                )
                if manifest_path:
                    call["_capture_manifest_path"] = manifest_path
                if capture_env is not None:
                    # The orchestrator reuses this mutable environment for
                    # the long capture. Only replace it after an audible probe
                    # so failed alternate attempts cannot corrupt its state.
                    capture_session_id = capture_env.get("STT_CAPTURE_SESSION_ID")
                    capture_env.clear()
                    capture_env.update(winning_environment)
                    if capture_session_id and "STT_CAPTURE_SESSION_ID" not in capture_env:
                        capture_env["STT_CAPTURE_SESSION_ID"] = capture_session_id
                return True, None

            # A positively identified event's waiting room is the desired
            # route. Do not exclude it or roam into older event/IR alternatives
            # merely because its scheduled audio has not started yet. The
            # scheduler's ordinary event-window retry revisits this route.
            wait_evidence = f"{result_error}\n{result.output}"
            if identity_verified and re.search(r"\bNOT_LIVE_YET\b", wait_evidence):
                wait_detail = next(
                    (line.strip() for line in wait_evidence.splitlines()
                     if re.search(r"\bNOT_LIVE_YET\b", line)),
                    "NOT_LIVE_YET verified event is waiting",
                )
                print(
                    f"[STTWorker] verified event waiting {call.get('ticker')} "
                    f"entrypoint={entrypoint_kind}; preserving route for next watch",
                    flush=True,
                )
                return False, f"{entrypoint_kind}: {wait_detail}"[:1000]

            errors.append(f"{entrypoint_kind}: {result_error}")
            self._cooldown_failed_entrypoint(
                call,
                entrypoint_kind,
                entrypoint_url,
                result_error,
            )
            discovered_targets = self._extract_live_target_urls(result.output)
            reason = classify_stream_failure(result_error)
            explicit_mismatch = bool(re.search(r"candidate (?:date|year|quarter|ticker).*contradict|TARGET_DATE_MISMATCH|EVENT_DATE_MISMATCH", result_error, re.I))
            reject_target = explicit_mismatch or (not identity_verified and bool(re.search(
                r"TARGET_UNCONFIRMED|TARGET_IDENTITY_UNCONFIRMED|CANDIDATE_NAVIGATION_FAILED|NOT_LIVE_YET", result_error, re.I)))
            new_targets = (discovered_targets - excluded_targets) if reject_target else set()
            excluded_targets.update(new_targets)
            protected_targets = live_runtime.remembered(call, {'auth_required', 'access_blocked', 'replay_source'})
            for target in discovered_targets:
                if target in protected_targets:
                    # Preserve the durable barrier recorded above; generic
                    # candidate notes must not shorten its operator cooldown.
                    continue
                with contextlib.suppress(OSError):
                    live_runtime.remember(call, target, "identity_mismatch" if explicit_mismatch else reason,
                                          ttl_seconds=180, identity_verified=identity_verified)
            # A proven correct event is retained when a later form/player/audio
            # stage fails. Its URL is not negative evidence about the event.
            if identity_verified and not explicit_mismatch and reason not in {'auth_required', 'access_blocked'}:
                with contextlib.suppress(OSError):
                    live_runtime.remember(call, entrypoint_url, "verified_stage_failed", ttl_seconds=180,
                                          error_code=classify_live_failure(result_error)["error_code"])


            # Retry the same entrypoint only when the browser actually reached
            # a concrete target. This avoids repeatedly hammering a bare IR
            # page that has no usable candidate at all.
            if new_targets and attempts < max_attempts:
                pending.append((entrypoint_kind, entrypoint_url))

            if pending and retry_delay:
                await asyncio.sleep(retry_delay)

        detail = " | ".join(errors[-4:])
        return False, f"live candidate loop exhausted: {detail}"[:1000]

    @staticmethod
    async def _drain_probe_output(
        stream: asyncio.StreamReader | None,
        output_tail: deque[str],
    ) -> None:
        """Drain a held Docker process continuously without retaining unbounded logs."""
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            output_tail.append(chunk.decode("utf-8", errors="replace"))

    @staticmethod
    def _probe_output_text(output_tail: deque[str]) -> str:
        return "".join(output_tail)

    async def _stop_promotable_probe(
        self,
        held: _PromotableProbeProcess,
    ) -> None:
        abort_path = self.host_runtime_artifact_path(held.abort_file)
        try:
            abort_path.parent.mkdir(parents=True, exist_ok=True)
            abort_path.touch()
        except OSError:
            pass
        try:
            # The shell first drains PCM (up to seven seconds), then reaps
            # Chromium's process group (up to five). A five-second TERM here
            # used to interrupt EXIT cleanup before its private Pulse daemon
            # was removed, leaving an orphan after otherwise normal aborts.
            cleanup_grace = self._cleanup_grace_seconds()
            await asyncio.wait_for(held.process.wait(), timeout=cleanup_grace)
        except TimeoutError:
            pid = getattr(held.process, "pid", None)
            try:
                if pid:
                    os.killpg(int(pid), signal.SIGTERM)
                else:
                    held.process.terminate()
            except (AttributeError, ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(held.process.wait(), timeout=cleanup_grace)
            except TimeoutError:
                try:
                    if pid:
                        os.killpg(int(pid), signal.SIGKILL)
                    else:
                        held.process.kill()
                except (AttributeError, ProcessLookupError, PermissionError):
                    pass
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(held.process.wait(), timeout=5)
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(asyncio.shield(held.output_task), timeout=2)

    @staticmethod
    async def _terminate_capture_process(
        process: asyncio.subprocess.Process,
        *,
        grace_seconds: float = 10.0,
    ) -> None:
        """Stop a capture whose DB lease no longer belongs to this worker."""
        if process.returncode is not None:
            return
        pid = getattr(process, "pid", None)
        try:
            if pid:
                os.killpg(int(pid), signal.SIGTERM)
            else:
                process.terminate()
        except (AttributeError, ProcessLookupError, PermissionError):
            with contextlib.suppress(AttributeError, ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=STTWorkerManager._cleanup_grace_seconds(grace_seconds))
            return
        except TimeoutError:
            pass
        try:
            if pid:
                os.killpg(int(pid), signal.SIGKILL)
            else:
                process.kill()
        except (AttributeError, ProcessLookupError, PermissionError):
            with contextlib.suppress(AttributeError, ProcessLookupError):
                process.kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)

    async def discard_promotable_probe(self, call: dict[str, Any]) -> bool:
        """Release a probe that cannot be promoted because capture was not claimed."""
        held = self._promotable_probes.pop(self._build_call_id(call), None)
        if held is None:
            return False
        await self._stop_promotable_probe(held)
        return True

    @staticmethod
    def _entrypoint_cooldown_key(
        call: dict[str, Any],
        entrypoint_kind: str,
        entrypoint_url: str,
    ) -> str:
        identity = str(call.get("id") or call.get("ticker") or "call")
        return hashlib.sha256(
            f"{identity}|{call.get('schedule_revision', 0)}|{entrypoint_kind}|{entrypoint_url}".encode("utf-8")
        ).hexdigest()

    def _cooldown_failed_entrypoint(
        self,
        call: dict[str, Any],
        entrypoint_kind: str,
        entrypoint_url: str,
        error: str,
    ) -> None:
        """Cool only the protected route, leaving alternate event URLs usable."""
        reason = classify_stream_failure(error)
        if reason == "auth_required":
            minutes = max(1, int(os.getenv("DATE_STREAM_AUTH_RETRY_MINUTES", "720")))
        elif reason == "access_blocked":
            minutes = max(1, int(os.getenv("DATE_STREAM_BLOCKED_RETRY_MINUTES", "360")))
        else:
            return
        key = self._entrypoint_cooldown_key(call, entrypoint_kind, entrypoint_url)
        self._entrypoint_retry_not_before[key] = time.monotonic() + minutes * 60
        with contextlib.suppress(OSError):
            live_runtime.remember(call, entrypoint_url, reason, ttl_seconds=minutes * 60)
        live_runtime.record(call, "discovery", "route_cooldown", status="operator_attention", route_url=entrypoint_url,
                            error_code=classify_live_failure(error)["error_code"], retry_after_seconds=minutes*60)

    def _probe_target_identity_verified(self, runtime_env: dict[str, str]) -> bool:
        if str(runtime_env.get("WEBCAST_LIVE_ENTRYPOINT_VERIFIED") or "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return True
        signal = self._read_runtime_file(
            runtime_env.get("WEBCAST_TARGET_IDENTITY_READY_FILE")
        )
        return bool(signal)

    def _verified_replay_source(self, call: dict[str, Any], runtime: dict[str, str]) -> dict | None:
        """Only a fresh, identity-bound current player can deny admission.

        An ended playlist, unknown source, or waiting music is insufficient.
        Checking the current player file also prevents a previous route in the
        same attempt from rejecting the newly selected route.
        """
        directory = call.get('_live_progress_dir')
        if not directory:
            return None
        source = read_progress_snapshot(directory).get('capture_source') or {}
        if (source.get('version') != 2 or source.get('replay_verified') is not True
                or source.get('target_identity_verified') is not True
                or source.get('capture_action') != 'reject_replay_route'
                or source.get('source_phase') != 'ended_replay_verified'):
            return None
        expected = {'call_id': call.get('id'), 'schedule_revision': call.get('schedule_revision', 0),
                    'attempt_id': call.get('_live_attempt_id'),
                    'capture_session_id': call.get('_capture_session_id')}
        if any(value is None or str(source.get(key)) != str(value) for key, value in expected.items()):
            return None
        try:
            stamp = datetime.fromisoformat(str(source.get('timestamp_utc') or source.get('timestamp')).replace('Z', '+00:00'))
            if stamp.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-stamp).total_seconds() <= 30:
                return None
        except (ValueError, TypeError):
            return None
        page = self._read_runtime_file(runtime.get('WEBCAST_ACTIVE_PLAYER_URL_FILE'))
        from ..collectors.streams.browser.navigation import same_event_route
        target = str(source.get('source_target_url') or '')
        # Public diagnostics redact signed query values. Recover the original
        # known route only when its exact fingerprint matches the observer.
        target_fingerprint = source.get('source_target_fingerprint')
        for original in ((call.get('_live_discovery_proof') or {}).get('target_url'),
                         call.get('webcast_url'), call.get('_live_entrypoint_url'), page):
            if original and hashlib.sha256(str(original).encode()).hexdigest()[:24] == target_fingerprint:
                target = str(original)
                break
        page_matches = bool(page and (same_event_route(page, str(source.get('source_page_url') or ''))
            or hashlib.sha256(page.encode()).hexdigest()[:24] == source.get('source_page_fingerprint')))
        if not page_matches or not target or not same_event_route(target, page):
            return None
        return {**source, 'source_target_url': target}

    def _remember_replay_source(self, call, source):
        self._discovery_cache.pop(self._build_call_id(call), None)
        target = source['source_target_url']
        live_runtime.remember(call, target, 'replay_source', ttl_seconds=43200,
            source_fingerprints=[row.get('media_source_fingerprint') for row in source.get('player_sources', [])],
            reason=source.get('replay_reason'))
        live_runtime.record(call, 'capture_source', 'replay_admission_rejected',
            status='rediscovery_required', target_url=target,
            error_code='VERIFIED_REPLAY_SOURCE', reason=source.get('replay_reason'))

    async def _probe_heartbeat_loop(self, call_id: Any) -> None:
        """Keep the DB lease alive without making browser probes DB-bound."""
        if not call_id:
            return
        interval = max(
            5.0,
            min(60.0, float(os.getenv("DATE_STREAM_PROBE_HEARTBEAT_SECONDS", "30"))),
        )
        while True:
            await asyncio.sleep(interval)
            try:
                try:
                    from .. import database
                except ImportError:
                    import database
                database.heartbeat_stream_probe(int(call_id))
            except Exception as exc:
                print(f"[STTWorker] probe heartbeat skipped: {exc}", flush=True)

    @staticmethod
    def _live_entrypoints(call: dict[str, Any]) -> list[tuple[str, str]]:
        """Return distinct live entrypoints, preferring pre-resolved URLs."""
        entrypoints: list[tuple[str, str]] = []
        seen: set[str] = set()
        rejected = STTWorkerManager._known_non_earnings_routes(call)
        routes = [("webcast_url", call.get("webcast_url")),
                  ("operator_event_url", live_runtime.operator_route(call)),
                  ("event_url", call.get("event_url")), ("ir_url", call.get("ir_url"))]
        for kind, raw in routes:
            value = str(raw or "").strip()
            if (not value or normalize_route(str(call.get("ir_url") or ""), value) != value
                    or value in seen or (kind != "ir_url" and value in rejected)):
                continue
            seen.add(value)
            entrypoints.append((kind, value))
        return entrypoints

    @staticmethod
    def _extract_live_target_urls(output: str) -> set[str]:
        """Extract concrete provider targets that can be excluded on retry."""
        patterns = (
            r"click target stabilized:\s*(https?://\S+)",
            r"webcast target opened:\s*(https?://\S+)",
            r"embedded webcast target opened:\s*(https?://\S+)",
            r"opening candidate href directly:\s*(https?://\S+)",
            r"opening direct replay candidate:\s*(https?://\S+)",
        )
        urls: set[str] = set()
        for pattern in patterns:
            for match in re.findall(pattern, output or "", flags=re.IGNORECASE):
                urls.add(match.rstrip(".,);]"))
        return urls

    @staticmethod
    def _capture_entrypoint(call: dict[str, Any]) -> str:
        """Use the entrypoint that passed the probe for the long capture."""
        return str(call.get("_live_entrypoint_url") or call.get("ir_url") or "")

    @staticmethod
    def _read_runtime_file(path_value: str | None) -> str:
        if not path_value:
            return ""
        try:
            path = STTWorkerManager.host_runtime_artifact_path(path_value)
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""

    @staticmethod
    def _read_runtime_json(path_value: str | None) -> Any:
        raw = STTWorkerManager._read_runtime_file(path_value)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _write_capture_manifest(
        self,
        call: dict[str, Any],
        capture_env: dict[str, str],
        result: WebcastProbeResult,
    ) -> str | None:
        """Persist the winning probe state used by the second capture process."""
        path_value = str(capture_env.get("WEBCAST_CAPTURE_MANIFEST_FILE") or "").strip()
        if not path_value:
            return None
        active_url = self._read_runtime_file(capture_env.get("WEBCAST_ACTIVE_PLAYER_URL_FILE"))
        last_target = self._read_runtime_file(capture_env.get("WEBCAST_LAST_TARGET_URL_FILE"))
        media_candidates = self._read_runtime_json(capture_env.get("WEBCAST_MEDIA_CANDIDATES_FILE"))
        recipe = self._read_runtime_json(capture_env.get("WEBCAST_RECIPE_CONTEXT_PATH"))
        probe_media_path = str(
            capture_env.get("WEBCAST_PROBE_MEDIA_CANDIDATES_FILE") or ""
        ).strip()
        if isinstance(media_candidates, list) and probe_media_path:
            try:
                path = self.host_runtime_artifact_path(probe_media_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(media_candidates, ensure_ascii=True),
                    encoding="utf-8",
                )
                temporary.replace(path)
            except OSError as exc:
                print(
                    f"[STTWorker] probe media handoff write skipped: {exc}",
                    flush=True,
                )
        manifest = {
            "version": 2,
            "created_at": time.time(),
            "ticker": str(call.get("ticker") or "").upper(),
            "call_id": self._build_call_id(call),
            "transcript_call_id": str(call.get("_capture_session_id") or ""),
            "call_year": call.get("call_year"),
            "quarter": call.get("quarter"),
            "target_date": self._target_event_date(call),
            "target_time_utc": self._target_event_time(call),
            "entrypoint_kind": call.get("_live_entrypoint_kind"),
            "entrypoint_url": call.get("_live_entrypoint_url") or self._capture_entrypoint(call),
            "target_identity_verified": (
                str(capture_env.get("WEBCAST_LIVE_ENTRYPOINT_VERIFIED") or "").lower()
                in {"1", "true", "yes", "on"}
            ),
            "schedule_source": call.get("schedule_source"),
            "schedule_discovery_fingerprint": call.get(
                "schedule_discovery_fingerprint"
            ),
            "excluded_urls": list(call.get("_live_excluded_urls") or []),
            "final_target_url": active_url or last_target or "",
            "media_candidates": media_candidates if isinstance(media_candidates, list) else [],
            "probe_media_candidates": probe_media_path,
            "recipe": recipe if isinstance(recipe, dict) else {},
            "audio_preflight_report": capture_env.get(
                "STT_AUDIO_PREFLIGHT_REPORT_FILE", ""
            ),
            "storage_state": capture_env.get("WEBCAST_STORAGE_STATE", ""),
            "save_storage_state": capture_env.get("WEBCAST_SAVE_STORAGE_STATE", ""),
            "probe_return_code": result.return_code,
        }
        path = self.host_runtime_artifact_path(path_value)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=True, default=str),
                encoding="utf-8",
            )
            temporary.replace(path)
            return path_value
        except OSError as exc:
            print(f"[STTWorker] capture manifest write skipped: {exc}", flush=True)
            return None

    def _attach_capture_session_to_manifest(
        self,
        manifest_path: str | None,
        capture_session_id: str,
    ) -> None:
        """Attach the STT session ID to the already-proven probe manifest."""
        if not manifest_path:
            return
        path = self.host_runtime_artifact_path(manifest_path)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                return
            current["transcript_call_id"] = capture_session_id
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(current, ensure_ascii=True, default=str),
                encoding="utf-8",
            )
            temporary.replace(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"[STTWorker] capture manifest session update skipped: {exc}", flush=True)

    async def probe_webcast_url(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str | None]:
        """Probe one URL in the browser-audio container without launching STT."""
        result = await self.probe_webcast_url_detailed(
            call,
            capture_env=capture_env,
            timeout_seconds=timeout_seconds,
        )
        return result.audible, result.error

    async def probe_webcast_url_detailed(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> WebcastProbeResult:
        """Probe one URL and preserve redacted browser/audio evidence for audits."""
        runtime: dict[str, str] | None = None
        if not call.get("ir_url"):
            return WebcastProbeResult(False, "missing IR URL", "", None)

        try:
            runtime = self._probe_runtime_environment(call, capture_env)
            for key in (
                "WEBCAST_PLAYBACK_READY_FILE",
                "WEBCAST_TARGET_IDENTITY_READY_FILE",
                "WEBCAST_ACTIVE_PLAYER_URL_FILE",
                "WEBCAST_LAST_TARGET_URL_FILE",
                "WEBCAST_MEDIA_CANDIDATES_FILE",
                "WEBCAST_PROBE_MEDIA_CANDIDATES_FILE",
                "WEBCAST_CAPTURE_MANIFEST_FILE",
                "WEBCAST_CAPTURE_LOG_FILE",
                "WEBCAST_LIVE_TERMINATION_FILE",
                "STT_AUDIO_PREFLIGHT_FILE",
                "STT_AUDIO_PREFLIGHT_REPORT_FILE",
                "WEBCAST_AUDIO_READY_FILE",
                "WEBCAST_PROBE_PROMOTE_FILE",
                "WEBCAST_PROBE_ABORT_FILE",
            ):
                path = str(runtime.get(key) or "").strip()
                if path:
                    try:
                        self.host_runtime_artifact_path(path).unlink(missing_ok=True)
                    except OSError:
                        pass
            command, process_env = self._probe_command(call, capture_env=capture_env)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=process_env,
                start_new_session=True,
            )
            timeout = self._probe_timeout_seconds(timeout_seconds)
            promotion_enabled = str(
                runtime.get("WEBCAST_PROBE_PROMOTION_ENABLED") or "false"
            ).lower() in {"1", "true", "yes", "on"}
            if promotion_enabled:
                output_tail: deque[str] = deque(maxlen=256)
                output_task = asyncio.create_task(
                    self._drain_probe_output(process.stdout, output_tail),
                    name=f"probe-output-{self._build_call_id(call)}",
                )
                wait_task = asyncio.create_task(process.wait())
                ready_path = self.host_runtime_artifact_path(
                    runtime["WEBCAST_AUDIO_READY_FILE"]
                )
                deadline = asyncio.get_running_loop().time() + timeout
                held = _PromotableProbeProcess(
                    process=process,
                    output_task=output_task,
                    output_tail=output_tail,
                    runtime_environment=runtime,
                    promote_file=runtime["WEBCAST_PROBE_PROMOTE_FILE"],
                    abort_file=runtime["WEBCAST_PROBE_ABORT_FILE"],
                )
                try:
                    while not ready_path.exists() and not wait_task.done():
                        if asyncio.get_running_loop().time() >= deadline:
                            await self._stop_promotable_probe(held)
                            text_output = self._probe_output_text(output_tail)
                            stage = self._probe_failure_stage(text_output)
                            return WebcastProbeResult(
                                False,
                                f"PROBE_TIMEOUT stage={stage} after {timeout:g}s",
                                text_output,
                                process.returncode,
                                runtime,
                            )
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    await self._stop_promotable_probe(held)
                    raise

                if ready_path.exists() and not wait_task.done():
                    wait_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await wait_task
                    process_key = self._build_call_id(call)
                    previous = self._promotable_probes.pop(process_key, None)
                    if previous is not None:
                        await self._stop_promotable_probe(previous)
                    self._promotable_probes[process_key] = held
                    return WebcastProbeResult(
                        True,
                        None,
                        self._probe_output_text(output_tail),
                        None,
                        runtime,
                    )

                await wait_task
                with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(asyncio.shield(output_task), timeout=2)
                text_output = self._probe_output_text(output_tail)
                return WebcastProbeResult(
                    False,
                    self._process_error(
                        text_output,
                        process.returncode,
                        operation="audio probe",
                    ),
                    text_output,
                    process.returncode,
                    runtime,
                )
            communicate_task = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=timeout)
            except asyncio.CancelledError:
                await self._terminate_probe_process(process, communicate_task)
                raise
            except TimeoutError:
                output, _ = await self._terminate_probe_process(process, communicate_task)
                text_output = (output or b"").decode("utf-8", errors="replace")
                stage = self._probe_failure_stage(text_output)
                detail = " | ".join(
                    line.strip() for line in text_output.splitlines()[-8:] if line.strip()
                )
                error = f"PROBE_TIMEOUT stage={stage} after {timeout:g}s"
                if detail:
                    error = f"{error}: {detail}"[:1000]
                return WebcastProbeResult(
                    False,
                    error,
                    text_output,
                    process.returncode,
                    runtime,
                )
        except Exception as exc:
            return WebcastProbeResult(False, str(exc), "", None, runtime)

        text_output = (output or b"").decode("utf-8", errors="replace")
        audio_signal_detected = (
            "AUDIO_DETECTED" in text_output
            and "NOT_LIVE_YET" not in text_output
            and "WEBCAST_EXITED_BEFORE_PLAYBACK" not in text_output
        )
        speech_pending = "SPEECH_NOT_DETECTED" in text_output
        # A replay can begin with music, a disclaimer, or a silent slide. Once
        # the player and Pulse route are proven, a short no-speech sample must
        # not erase that valid webcast access or restart candidate discovery.
        # Exit code 71 is retained for compatibility with an older probe helper
        # that used it solely for this no-speech outcome.
        audio_ready = audio_signal_detected and (
            process.returncode == 0 or speech_pending
        )
        if audio_ready:
            return WebcastProbeResult(
                True,
                None,
                text_output,
                process.returncode,
                runtime,
            )
        return WebcastProbeResult(
            False,
            self._process_error(
                text_output,
                process.returncode,
                operation="audio probe",
            ),
            text_output,
            process.returncode,
            runtime,
        )

    async def learn_webcast_url(
        self,
        call: dict[str, Any],
        *,
        timeout_seconds: float = 60,
    ) -> tuple[bool, str | None]:
        """Learn a future event page's navigation without treating pre-live silence as failure."""
        if not call.get("ir_url"):
            return False, "missing IR URL"

        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            command = [
                "python",
                "-m",
                "data_pipeline.collectors.streams.browser_webcast",
                "--ticker",
                str(call["ticker"]).upper(),
                "--ir-url",
                str(call["ir_url"]),
            ]
        else:
            repository_root = Path(__file__).resolve().parents[2]
            compose_file = repository_root / "infra" / "docker-compose.yml"
            command = [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "--profile",
                "tools",
                "run",
                "--rm",
                "browser-webcast",
                "python",
                "-m",
                "data_pipeline.collectors.streams.browser_webcast",
                "--ticker",
                str(call["ticker"]).upper(),
                "--ir-url",
                str(call["ir_url"]),
            ]

        try:
            process_env = None
            if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() != "container":
                process_env = {
                    **os.environ,
                    "COMPOSE_IGNORE_ORPHANS": "1",
                }
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=process_env,
                start_new_session=True,
            )
            communicate_task = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=timeout_seconds)
            except TimeoutError:
                output, _ = await self._terminate_probe_process(
                    process,
                    communicate_task,
                )
                return False, f"discovery timed out after {timeout_seconds:g}s"
        except Exception as exc:
            return False, str(exc)

        text_output = (output or b"").decode("utf-8", errors="replace")
        if process.returncode == 0:
            return True, None
        return False, self._process_error(text_output, process.returncode, operation="webcast discovery")

    def _probe_command(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None,
    ) -> tuple[list[str], dict[str, str] | None]:
        """Use Docker from the host or the local audio script inside a worker container."""
        runtime_env = self._probe_runtime_environment(call, capture_env)
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() != "container":
            return self._build_audio_capture_command(
                call,
                probe_only=True,
                capture_env=runtime_env,
            ), {
                **os.environ,
                # Visible-mode containers may intentionally remain alive while
                # a headless audit starts. Do not let Compose's orphan warning
                # become browser-probe noise or look like a probe failure.
                "COMPOSE_IGNORE_ORPHANS": "1",
            }

        command = [
            "bash",
            "data_pipeline/scripts/run_webcast_audio_capture.sh",
            "--probe-only",
            str(call["ticker"]).upper(),
            self._capture_entrypoint(call),
        ]
        environment = {**os.environ, **runtime_env}
        environment["CALL_ID"] = str(
            runtime_env.get("STT_CAPTURE_SESSION_ID") or self._build_call_id(call)
        )
        return command, environment

    @staticmethod
    def _probe_runtime_environment(
        call: dict[str, Any],
        capture_env: dict[str, str] | None,
    ) -> dict[str, str]:
        """Give concurrent probes isolated PulseAudio and browser handshake paths."""
        ticker = re.sub(r"[^A-Za-z0-9]", "", str(call.get("ticker") or "probe").upper())[:12] or "PROBE"
        target_hash = hashlib.sha1(
            "|".join(
                [
                    str(call.get("id") or call.get("call_id") or ""),
                    str(call.get("ticker") or ticker),
                    str(call.get("call_year") or ""),
                    str(call.get("quarter") or ""),
                    str(call.get("ir_url") or call.get("target_url") or ticker),
                ]
            ).encode("utf-8")
        ).hexdigest()[:10]
        # Browser probes run in a Docker container with the repository mounted at
        # /app. Keep handshake artifacts in that shared mount so the host worker
        # can learn the final event/player URL after the container exits.
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            artifact_root = Path(__file__).resolve().parents[1] / ".runtime" / "operations" / "probe-artifacts"
        else:
            artifact_root = Path("/app/data_pipeline/.runtime/operations/probe-artifacts")
        attempt_suffix = ("-" + str(call["_live_attempt_id"]) + "-" + str(call.get("_live_route_attempt", 0))) if call.get("_live_attempt_id") else ""
        prefix = str(artifact_root / f"ew-webcast-{ticker.lower()}-{target_hash}{attempt_suffix}")
        # Evidence is unique per attempt, but a valid waiting-room login must
        # survive the next attempt for the same call, revision and route.
        storage_prefix = (str(artifact_root / f"ew-webcast-{ticker.lower()}-{target_hash}-r{int(call.get('schedule_revision') or 0)}")
                          if call.get('_live_attempt_id') else prefix)
        # A replacement attempt must not reuse a still-exiting attempt's
        # PulseAudio daemon: its EXIT trap owns and removes that runtime.
        # Keep the login state key above stable, but scope audio to the
        # attempt and route. Rebuilding the same environment remains stable
        # so probe promotion keeps the already playing browser and monitor.
        audio_attempt = "|".join((
            str(call.get("_live_attempt_id") or ""),
            str(call.get("_live_route_attempt") or 0),
            str((capture_env or {}).get("STT_CAPTURE_SESSION_ID")
                or call.get("_capture_session_id") or ""),
        ))
        audio_hash = hashlib.sha256(audio_attempt.encode("utf-8")).hexdigest()[:10]
        sink = f"ew_webcast_{ticker.lower()}_{target_hash}_{audio_hash}"
        runtime_env = dict(capture_env or {})
        if call.get("_live_attempt_id"):
            runtime_env.update(live_runtime.prepare_attempt(call))
        entrypoint_kind = str(call.get("_live_entrypoint_kind") or "").strip()
        selected_url = str(call.get("_live_entrypoint_url") or call.get("ir_url") or "")
        discovery_proof = call.get("_live_discovery_proof")
        if not STTWorkerManager._fresh_discovery_proof(call, selected_url, discovery_proof):
            discovery_proof = (STTWorkerManager._stored_target_proof(call)
                               or STTWorkerManager._remembered_target_proof(call))
        official_entrypoint = (
            entrypoint_kind in {"event_url", "webcast_url"}
            and STTWorkerManager._fresh_discovery_proof(call, selected_url, discovery_proof)
        )
        if official_entrypoint:
            runtime_env["WEBCAST_LIVE_IDENTITY_PROOF"] = json.dumps(discovery_proof)
        else:
            runtime_env.pop("WEBCAST_LIVE_IDENTITY_PROOF", None)
        configured_storage_state = str(
            runtime_env.get("WEBCAST_STORAGE_STATE") or ""
        ).strip()
        configured_save_storage_state = str(
            runtime_env.get("WEBCAST_SAVE_STORAGE_STATE") or ""
        ).strip()
        runtime_env.update(
            {
                "WEBCAST_PULSE_SINK": sink,
                "STT_INPUT_SOURCE": f"{sink}.monitor",
                # Managed captures always own a private Pulse runtime and
                # auto-allocated Xvfb display. Do not inherit a desktop/shared
                # daemon or the manual viewer's fixed display/VNC ports.
                "WEBCAST_PULSE_RUNTIME_DIR": "",
                "WEBCAST_XDG_RUNTIME_DIR": "",
                "WEBCAST_VNC_ENABLED": "false",
                "WEBCAST_USE_HOST_DISPLAY": "false",
                "WEBCAST_PLAYBACK_READY_FILE": f"{prefix}-playback-ready",
                "WEBCAST_TARGET_IDENTITY_READY_FILE": f"{prefix}-target-identity-ready",
                "WEBCAST_ACTIVE_PLAYER_URL_FILE": f"{prefix}-active-url",
                "WEBCAST_LAST_TARGET_URL_FILE": f"{prefix}-last-target-url",
                "WEBCAST_MEDIA_CANDIDATES_FILE": f"{prefix}-media-candidates.json",
                # The capture browser clears its own discovery file on startup.
                # Preserve successful probe candidates separately so an HLS/MP4
                # fallback can still use the exact source that was audible.
                "WEBCAST_PROBE_MEDIA_CANDIDATES_FILE": f"{prefix}-probe-media-candidates.json",
                "WEBCAST_RECIPE_CONTEXT_PATH": f"{prefix}-recipe.json",
                "WEBCAST_CAPTURE_MANIFEST_FILE": f"{prefix}-capture-manifest.json",
                "WEBCAST_CAPTURE_LOG_FILE": f"{prefix}-capture.log",
                "WEBCAST_LIVE_TERMINATION_FILE": f"{prefix}-live-termination.json",
                "WEBCAST_MEDIA_FALLBACK_LOG_FILE": f"{prefix}-media-fallback.log",
                "WEBCAST_YTDLP_LOG_FILE": f"{prefix}-yt-dlp.log",
                "WEBCAST_YOUTUBE_FFMPEG_LOG_FILE": f"{prefix}-youtube-ffmpeg.log",
                "STT_AUDIO_PREFLIGHT_CAPTURE_LOG_FILE": f"{prefix}-preflight-capture.log",
                "WEBCAST_AUDIO_READY_FILE": f"{prefix}-audio-ready",
                "WEBCAST_PROBE_PROMOTE_FILE": f"{prefix}-promote",
                "WEBCAST_PROBE_ABORT_FILE": f"{prefix}-abort",
                "STT_AUDIO_PREFLIGHT_FILE": f"{prefix}-audio-preflight.wav",
                "STT_AUDIO_PREFLIGHT_REPORT_FILE": f"{prefix}-audio-preflight.json",
                # An explicit state is an authenticated input (for example the
                # Q4 state captured in visible mode). Keep it for reads, but
                # always save a per-call state unless the caller says otherwise.
                "WEBCAST_STORAGE_STATE": configured_storage_state or f"{storage_prefix}-storage.json",
                "WEBCAST_SAVE_STORAGE_STATE": (
                    configured_save_storage_state or f"{storage_prefix}-storage.json"
                ),
                "WEBCAST_TARGET_YEAR": str(call.get("verified_fiscal_year") or (call.get("call_year") if call.get("replay_target_url") else "") or ""),
                "WEBCAST_TARGET_QUARTER": str(call.get("verified_fiscal_quarter") or (call.get("quarter") if call.get("replay_target_url") else "") or ""),
                # Use the issuer's event date for candidate ranking. The
                # browser still performs the final live-state check itself.
                "WEBCAST_TARGET_DATE": STTWorkerManager._target_event_date(call),
                "WEBCAST_TARGET_TIME_UTC": STTWorkerManager._target_event_time(call),
                "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": (
                    "true" if official_entrypoint else "false"
                ),
                # Historical candidate retries keep the original IR URL for
                # classification, while the browser opens this exact replay
                # page directly.
                "WEBCAST_DIRECT_TARGET_URL": str(
                    call.get("replay_target_url") or ""
                ).strip(),
            }
        )
        return runtime_env

    @staticmethod
    def _target_event_date(call: dict[str, Any]) -> str:
        """Return the stored issuer-local event date in ISO form when available."""
        value = call.get("webcast_date") or call.get("earning_at")
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return str(value.isoformat())[:10]
        return str(value).strip()[:10]

    @staticmethod
    def _target_event_time(call: dict[str, Any]) -> str:
        """Return the verified UTC event start for live candidate checks."""
        value = call.get("scheduled_at_utc")
        if call.get("schedule_time_stale") or value is None:
            return ""
        if hasattr(value, "isoformat"):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    async def launch_date_based_audio_capture(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
    ) -> None:
        """Start the long-running browser audio/STT container after an audible probe."""
        call = dict(call)
        call_id = self._build_call_id(call)
        capture_session_id = str(
            call.get("_capture_session_id")
            or (capture_env or {}).get("STT_CAPTURE_SESSION_ID")
            or self.build_capture_session_id(call)
        )[:128]
        call["_capture_session_id"] = capture_session_id
        held = self._promotable_probes.get(call_id)
        admission_environment = {**(held.runtime_environment if held is not None else {}),
                                 **(capture_env or {})}
        replay = self._verified_replay_source(call, admission_environment)
        if replay:
            self._remember_replay_source(call, replay)
            await self.discard_promotable_probe(call)
            raise RuntimeError('VERIFIED_REPLAY_SOURCE admission changed before promotion')
        existing = self._active_processes.get(call_id)
        if existing and existing.returncode is None:
            print(f"[STTWorker] {call['ticker']} already running call_id={call_id}")
            return

        held = self._promotable_probes.get(call_id)
        if held is not None and held.process.returncode is None:
            launch_environment = {
                "WEBCAST_LIFECYCLE": "live",
                **held.runtime_environment,
                **(capture_env or {}),
                "STT_CAPTURE_SESSION_ID": capture_session_id,
            }
            manifest_path = launch_environment.get("WEBCAST_CAPTURE_MANIFEST_FILE")
            capture_log_path = launch_environment.get("WEBCAST_CAPTURE_LOG_FILE")
            if capture_log_path:
                call["_capture_log_path"] = capture_log_path
            self._attach_capture_session_to_manifest(manifest_path, capture_session_id)
            if call.get("id") and manifest_path:
                try:
                    try:
                        from .. import database
                    except ImportError:
                        import database
                    database.update_capture_manifest(call["id"], manifest_path)
                except Exception as exc:
                    print(
                        f"[STTWorker] failed to persist capture manifest path: {exc}",
                        flush=True,
                    )
            promote_path = self.host_runtime_artifact_path(held.promote_file)
            try:
                promote_path.parent.mkdir(parents=True, exist_ok=True)
                promote_path.touch()
            except (OSError, ValueError):
                self._promotable_probes.pop(call_id, None)
                await self._stop_promotable_probe(held)
                raise
            self._promotable_probes.pop(call_id, None)
            self._active_processes[call_id] = held.process
            print(
                f"[STTWorker] promoted audible probe in place for "
                f"{call['ticker']} call_id={call_id}",
                flush=True,
            )
            asyncio.create_task(
                self._watch_process(
                    call,
                    call_id,
                    held.process,
                    output_task=held.output_task,
                )
            )
            return
        if held is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(held.output_task), timeout=2)

        launch_environment = {
            "WEBCAST_LIFECYCLE": "live",
            **(capture_env or {}),
        }
        launch_environment["STT_CAPTURE_SESSION_ID"] = capture_session_id
        excluded_urls = call.get("_live_excluded_urls") or []
        if excluded_urls and not launch_environment.get("WEBCAST_LIVE_EXCLUDED_URLS"):
            launch_environment["WEBCAST_LIVE_EXCLUDED_URLS"] = ",".join(
                str(url) for url in excluded_urls if str(url).strip()
            )
        command = self._build_audio_capture_command(
            call,
            probe_only=False,
            capture_env=launch_environment,
        )
        print(f"[STTWorker] launching browser audio capture for {call['ticker']} call_id={call_id}")
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            process_env = {
                **os.environ,
                **launch_environment,
                "CALL_ID": capture_session_id,
            }
        else:
            process_env = {
                **os.environ,
                "COMPOSE_IGNORE_ORPHANS": "1",
            }
        process = await asyncio.create_subprocess_exec(
            *command,
            env=process_env,
            start_new_session=True,
        )
        self._active_processes[call_id] = process
        manifest_path = launch_environment.get("WEBCAST_CAPTURE_MANIFEST_FILE")
        capture_log_path = launch_environment.get("WEBCAST_CAPTURE_LOG_FILE")
        if capture_log_path:
            call["_capture_log_path"] = capture_log_path
        self._attach_capture_session_to_manifest(manifest_path, capture_session_id)
        if call.get("id") and manifest_path:
            try:
                try:
                    from .. import database
                except ImportError:
                    import database
                database.update_capture_manifest(call["id"], manifest_path)
            except Exception as exc:
                print(f"[STTWorker] failed to persist capture manifest path: {exc}", flush=True)
        asyncio.create_task(self._watch_process(call, call_id, process))

    async def wait_for_active_processes(self, timeout_seconds: float = 120) -> dict[str, int | None]:
        """Wait for currently launched workers; useful for end-to-end verification."""
        active = list(self._active_processes.items())
        if not active:
            return {}

        async def wait_one(call_id: str, process: asyncio.subprocess.Process) -> tuple[str, int | None]:
            return call_id, await process.wait()

        results = await asyncio.wait_for(
            asyncio.gather(*(wait_one(call_id, process) for call_id, process in active)),
            timeout=max(1.0, timeout_seconds),
        )
        return dict(results)

    def _build_audio_capture_command(
        self,
        call: dict[str, Any],
        *,
        probe_only: bool,
        capture_env: dict[str, str] | None = None,
    ) -> list[str]:
        """Build a host-side Docker command so Chromium always has supported libraries."""
        repository_root = Path(__file__).resolve().parents[2]
        compose_file = repository_root / "infra" / "docker-compose.yml"
        call_id = str(
            (capture_env or {}).get("STT_CAPTURE_SESSION_ID")
            or call.get("_capture_session_id")
            or self._build_call_id(call)
        )
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            command = [
                "bash",
                "data_pipeline/scripts/run_webcast_audio_capture.sh",
            ]
            if probe_only:
                command.append("--probe-only")
            command.extend([str(call["ticker"]).upper(), self._capture_entrypoint(call)])
            return command

        command = [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--profile",
            "tools",
            "run",
            "--rm",
            "-e",
            f"CALL_ID={call_id}",
        ]
        for key, value in sorted((capture_env or {}).items()):
            command.extend(["-e", f"{key}={value}"])
        command.extend([
            "browser-webcast",
            "data_pipeline/scripts/run_webcast_audio_capture.sh",
        ])
        if probe_only:
            command.append("--probe-only")
        command.extend([str(call["ticker"]).upper(), self._capture_entrypoint(call)])
        return command

    @staticmethod
    def _process_error(
        output: str,
        return_code: int | None,
        *,
        operation: str = "audio probe",
    ) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        detail = " | ".join(lines[-8:])
        if not detail:
            detail = "audio was not detected"
        return f"{operation} failed (exit={return_code}): {detail}"[:1000]

    def _capture_failure_detail(self, call: dict[str, Any]) -> str | None:
        """Return failure evidence from the browser/STT supervisor artifact."""
        path_value = str(call.get("_capture_log_path") or "").strip()
        if not path_value:
            return None
        try:
            output = self.host_runtime_artifact_path(path_value).read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None
        # The final live outcome is more useful than an earlier successful
        # registration form or playback message in this same capture log.
        lifecycle = [line.strip() for line in output.splitlines() if re.search(
            r"(?:STT_LIVE_INCOMPLETE|reason=live_[a-z_]+|LIVE_SOURCE_LOST)", line
        )]
        if lifecycle:
            return " | ".join(lifecycle[-3:])[:700]
        interesting = [
            line.strip()
            for line in output.splitlines()
            if re.search(
                r"(?:AUTH_REQUIRED|REGISTRATION_REQUIRED|CAPTCHA|human verification|"
                r"email (?:login )?link|registration (?:has|field|submission|submit|form)|"
                r"access denied|blocked|"
                r"cloudflare|forbidden|rate limit|too many requests|http 40[39]|"
                r"PLAYBACK_READY|AUDIO_NOT_DETECTED|WEBCAST_EXITED)",
                line,
                re.IGNORECASE,
            )
        ]
        if not interesting:
            return None
        return " | ".join(interesting[-6:])[:700]

    def _build_call_id(self, call) -> str:
        ticker = str(call["ticker"]).upper()
        year = call.get("call_year")
        quarter = call.get("quarter")
        if year and quarter:
            return f"{ticker}-{year}{quarter}"
        if call.get("id"):
            return f"{ticker}-call-{call['id']}"
        return ticker

    @staticmethod
    def build_capture_session_id(call: dict[str, Any]) -> str:
        """Create a per-run transcript key so old text cannot prove a new capture."""
        ticker = re.sub(r"[^A-Za-z0-9]", "", str(call.get("ticker") or "call").upper())
        ticker = ticker[:20] or "CALL"
        call_id = str(call.get("id") or "unknown")[:32]
        return f"{ticker}-capture-{call_id}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _infer_call_quarter(call: dict[str, Any]) -> str | None:
        configured = str(call.get("quarter") or "").strip()
        if configured:
            return configured
        source = " ".join(
            str(call.get(key) or "")
            for key in ("ir_url", "target_url", "source_title")
        )
        match = re.search(r"(?:^|[^a-z])q([1-4])(?:[^a-z]|$)", source, re.IGNORECASE)
        return f"Q{match.group(1)}" if match else None

    def _build_command(self, call, call_id: str) -> list[str]:
        ticker = str(call["ticker"]).upper()
        source = call.get("video_url")
        input_kind = os.getenv("STT_WORKER_INPUT_KIND")
        if not input_kind:
            input_kind = "url" if source else "device"

        command = [
            sys.executable,
            "-m",
            "data_pipeline.stt_worker.take",
            "--ticker",
            ticker,
            "--call-id",
            call_id,
            "--input-kind",
            input_kind,
        ]
        if source and input_kind == "url":
            command.extend(["--input-source", str(source)])
        elif os.getenv("STT_INPUT_SOURCE"):
            command.extend(["--input-source", os.getenv("STT_INPUT_SOURCE", "")])
        if os.getenv("STT_WORKER_DRY_RUN", "false").lower() == "true":
            command.append("--print-ffmpeg-command")
        return command

    async def _resolve_webcast_source(self, call: dict[str, Any]) -> None:
        if call.get("video_url"):
            return
        if not call.get("ir_url"):
            return
        if os.getenv("STT_WEBCAST_DISCOVERY_ENABLED", "true").lower() != "true":
            return

        requested_input_kind = os.getenv("STT_WORKER_INPUT_KIND", "").lower()
        if requested_input_kind and requested_input_kind != "url":
            return

        try:
            try:
                from ..collectors.streams.browser_webcast import BrowserWebcastAgent
            except ImportError:
                from data_pipeline.collectors.streams.browser_webcast import BrowserWebcastAgent

            hold_seconds = float(
                os.getenv(
                    "WEBCAST_DISCOVERY_HOLD_SECONDS",
                    os.getenv("WEBCAST_HOLD_SECONDS", "5"),
                )
            )
            agent = BrowserWebcastAgent(
                str(call["ticker"]),
                str(call["ir_url"]),
                headless=os.getenv("WEBCAST_HEADLESS", "true").lower() != "false",
                hold_seconds=hold_seconds,
                target_year=call.get("call_year"),
                target_quarter=self._infer_call_quarter(call),
            )
            result = await agent.run()
        except Exception as exc:
            raise RuntimeError(f"webcast discovery failed: {exc}") from exc

        if not result.success:
            raise RuntimeError(f"webcast discovery failed: {result.error}")
        if not result.media_candidates:
            raise RuntimeError("webcast discovery did not capture a media URL")

        video_url = result.media_candidates[0]
        call["video_url"] = video_url
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if call.get("id"):
                database.update_call_video_url(call["id"], video_url)
        except Exception as exc:
            print(f"[STTWorker] failed to persist discovered media URL: {exc}")

    @staticmethod
    def _progress_alerts(snapshots: dict, elapsed_seconds: float) -> list[tuple[str, str, dict]]:
        warnings = []
        now = datetime.now(timezone.utc)
        for stage, value in snapshots.items():
            if value.get('warning') is True or value.get('status') in {'warning', 'error', 'stalled', 'operator_attention'}:
                warnings.append((stage, value.get('event') or 'progress_warning', value))
            if stage in {'stt', 'audio', 'playback'}:
                try:
                    observed = datetime.fromisoformat(str(value.get('timestamp_utc') or value.get('timestamp')).replace('Z', '+00:00'))
                    if (now - observed).total_seconds() > 45:
                        warnings.append((stage, 'PROGRESS_HEARTBEAT_STALE', value))
                except (ValueError, TypeError):
                    warnings.append((stage, 'PROGRESS_TIMESTAMP_INVALID', value))
        if elapsed_seconds >= 60 and not snapshots.get('stt'):
            warnings.append(('stt', 'STT_PROGRESS_MISSING', {'status': 'warning'}))
        stt = snapshots.get('stt') or {}
        try:
            if float(stt.get('backlog_seconds') or 0) >= 120:
                warnings.append(('stt', 'STT_AUDIO_BACKLOG', stt))
        except (ValueError, TypeError):
            pass
        return warnings

    async def _monitor_live_capture(self, call: dict[str, Any], process, finished) -> None:
        """Observe progress independently of Whisper; never kill a music waiting room."""
        directory = call.get('_live_progress_dir')
        if not directory:
            return
        last_alert: dict[str, float] = {}
        started = time.monotonic()
        while not finished.done():
            try:
                request = live_runtime.consume_request(call, 'retry')
                if request:
                    call['_operator_retry_requested'] = True
                    live_runtime.record(call, 'capture', 'operator_retry', status='stopping', request_id=request.get('request_id'))
                    await self._terminate_capture_process(process)
                    return
                snapshots = read_progress_snapshot(directory)
                warnings = self._progress_alerts(snapshots, time.monotonic()-started)
                for stage, code, value in warnings:
                    key = f'{stage}:{code}'
                    if time.monotonic()-last_alert.get(key, 0) < 30:
                        continue
                    last_alert[key] = time.monotonic()
                    from ..operations import record_event
                    record_event('live_progress_stalled', ticker=call.get('ticker'), call_id=call.get('id'),
                                 status='warning', stage=stage, error_code=code,
                                 capture_session_id=call.get('_capture_session_id'),
                                 schedule_revision=call.get('schedule_revision'), attempt_id=call.get('_live_attempt_id'),
                                 artifact_path=str(Path(directory)/f'{stage}.json'),
                                 audio_condition=value.get('audio_condition'),
                                 backlog_seconds=value.get('backlog_seconds'),
                                 last_progress_at=value.get('last_progress_at'),
                                 action='inspect_stage_preserve_recording')
                    print(f"[LiveProgress] {call.get('ticker')} stage={stage} warning={code} evidence={directory}", flush=True)
            except Exception as exc:
                print(f'[LiveProgress] observation deferred: {type(exc).__name__}', flush=True)
            await asyncio.sleep(max(1., float(os.getenv('WEBCAST_PROGRESS_POLL_SECONDS', '5'))))

    async def _watch_process(
        self,
        call,
        call_id: str,
        process: asyncio.subprocess.Process,
        *,
        output_task: asyncio.Task[None] | None = None,
    ) -> None:
        capture_session_id = str(call.get("_capture_session_id") or "").strip() or None
        wait_task = asyncio.create_task(process.wait())
        progress_task = asyncio.create_task(self._monitor_live_capture(call, process, wait_task))
        heartbeat_seconds = max(
            0.1,
            float(os.getenv("DATE_STREAM_CAPTURE_HEARTBEAT_SECONDS", "30")),
        )
        try:
            while not wait_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(wait_task),
                        timeout=heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    if call.get("id"):
                        try:
                            try:
                                from .. import database
                            except ImportError:
                                import database
                            ownership_retained = database.heartbeat_call_capture(
                                call["id"],
                                capture_session_id=capture_session_id,
                            )
                            if ownership_retained is False:
                                print(
                                    f"[STTWorker] capture lease lost; terminating "
                                    f"call_id={call_id} session={capture_session_id}",
                                    flush=True,
                                )
                                await self._terminate_capture_process(process)
                        except Exception as exc:
                            print(f"[STTWorker] capture heartbeat skipped: {exc}", flush=True)
            return_code = await wait_task
        finally:
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task
        if output_task is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(output_task), timeout=2)
        if self._active_processes.get(call_id) is process:
            self._active_processes.pop(call_id, None)
        status = "completed" if return_code == 0 else "failed"
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if call.get("id"):
                if return_code == 0 and capture_session_id:
                    proof = database.complete_call_capture_from_transcript(
                        call["id"],
                        capture_session_id,
                    )
                    if bool(proof.get("completed")):
                        status = "completed"
                    else:
                        if bool(proof.get("ownership_lost")):
                            reason = "capture session ownership was lost before completion"
                        elif int(proof.get("segment_count") or 0) == 0:
                            reason = "capture exited without archived STT segments"
                        elif int(proof.get("segment_count") or 0) < int(
                            proof.get("minimum_segment_count") or 1
                        ):
                            reason = (
                                "capture transcript was too short: "
                                f"segments={int(proof.get('segment_count') or 0)} "
                                f"required={int(proof.get('minimum_segment_count') or 1)}"
                            )
                        elif int(proof.get("text_character_count") or 0) < int(
                            proof.get("minimum_text_character_count") or 1
                        ):
                            reason = (
                                "capture transcript contained too little text: "
                                f"characters={int(proof.get('text_character_count') or 0)} "
                                "required="
                                f"{int(proof.get('minimum_text_character_count') or 1)}"
                            )
                        elif int(proof.get("session_end_count") or 0) == 0:
                            reason = "capture exited without an archived STT session-end marker"
                        elif int(proof.get("successful_end_count") or 0) == 0:
                            outcome = str(
                                proof.get("session_end_reason") or "unclassified"
                            )
                            reason = f"capture ended without success eligibility: {outcome}"
                        elif int(proof.get("identity_verified_end_count") or 0) == 0:
                            reason = "capture transcript target identity was not verified"
                        elif int(proof.get("valid_end_count") or 0) == 0:
                            reason = (
                                "LIVE_CAPTURE_INCOMPLETE capture has no confirmed event end: "
                                + str(proof.get("session_end_reason") or "unknown")
                            )
                        else:
                            reason = "capture transcript proof was incomplete"
                        retry_scheduled = database.requeue_failed_call_capture(
                            call["id"],
                            error=reason,
                            capture_session_id=capture_session_id,
                        )
                        status = "retry_pending" if retry_scheduled else "failed"
                elif return_code == 0:
                    # A zero exit code only proves that the subprocess stopped.
                    # Legacy callers must provide the same session proof as the
                    # date-based live path before a call can be completed.
                    retry_scheduled = database.requeue_failed_call_capture(
                        call["id"],
                        error="capture exited without a durable capture session",
                    )
                    status = "retry_pending" if retry_scheduled else "failed"
                else:
                    retry_kwargs: dict[str, str] = {}
                    if capture_session_id:
                        retry_kwargs["capture_session_id"] = capture_session_id
                    failure_detail = self._capture_failure_detail(call)
                    error = f"capture process exited with code {return_code}"
                    if return_code in {70, 71, 74, 76, 77, 78, 79} or call.get("_operator_retry_requested"):
                        error = f"LIVE_CAPTURE_INCOMPLETE {error}"
                    if failure_detail:
                        error = f"{error}: {failure_detail}"
                    retry_scheduled = database.requeue_failed_call_capture(
                        call["id"],
                        error=error,
                        **retry_kwargs,
                    )
                    status = "retry_pending" if retry_scheduled else "failed"
        except Exception as exc:
            print(f"[STTWorker] failed to persist status for call_id={call_id}: {exc}")
        live_runtime.record(call, "capture", "capture_finished", status=status, return_code=return_code,
                            terminal=True, progress=True)
        print(f"[STTWorker] {call_id} exited code={return_code} status={status}")
