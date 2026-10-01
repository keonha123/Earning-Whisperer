"""Passive source diagnostics; event identity and live delivery are separate facts.

No request or capture action is issued by this observer. Finalized media alone
may be waiting music and never authorizes rejection. Explicit, source-bound
replay evidence is advisory input to the manager's fresh, same-route admission
check. Advancing transport alone does not prove live speech or live-edge audio.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
import hashlib
import math
import time
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from data_pipeline.live_telemetry import emit_live_event
from .navigation import same_event_route

MAX_PLAYLIST_BYTES = 262144


def _public_event_url(url: str) -> str:
    """Only public event identifiers survive; credentials/signatures never do."""
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return ''
    safe = {'event', 'eventid', 'event_id', 'id', 'ei', 'webcastid', 'webcast_id', 'companyid', 'locale', 'lang'}
    query = [(key, value if key.lower() in safe else '[redacted]')
             for key, value in parse_qsl(parsed.query)]
    authority = parsed.hostname + (':' + str(parsed.port) if parsed.port else '')
    return urlunsplit((parsed.scheme, authority, parsed.path, urlencode(query), ''))


def media_source_descriptor(url: str) -> dict:
    """Hash the exact selected source; never persist a signed media URL."""
    value = str(url or '')
    parsed = urlsplit(value)
    path = parsed.path.lower()
    kind = ('blob' if parsed.scheme == 'blob' else
            'hls' if path.endswith('.m3u8') else
            'file' if path.endswith(('.mp4', '.m4a', '.mp3', '.webm', '.ogg', '.wav'))
            else 'unknown')
    return {'media_source_fingerprint': hashlib.sha256(value.encode()).hexdigest()[:24] if value else None,
            'media_source_kind': kind,
            'media_source_is_http': parsed.scheme in {'http', 'https'}}


def playlist_summary(body: str) -> dict | None:
    """Keep timing/sequence evidence only; discard media URLs and auth tokens."""
    if len(body) > MAX_PLAYLIST_BYTES or not body.lstrip().startswith('#EXTM3U'):
        return None
    durations, segments = [], []
    sequence = None
    program_time = None
    program_offset = 0.0
    endlist = False
    playlist_type = None
    try:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith('#EXTINF:'):
                value = float(line.split(':', 1)[1].split(',', 1)[0])
                if not math.isfinite(value) or value <= 0:
                    return None
                durations.append(value)
            elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                sequence = int(line.split(':', 1)[1])
                if sequence < 0:
                    return None
            elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
                parsed = datetime.fromisoformat(line.split(':', 1)[1].replace('Z', '+00:00'))
                if parsed.tzinfo is not None:
                    program_time = parsed.timestamp()
                    program_offset = sum(durations)
            elif line.startswith('#EXT-X-PLAYLIST-TYPE:'):
                playlist_type = line.split(':', 1)[1].strip().upper()
            elif line == '#EXT-X-ENDLIST':
                endlist = True
            elif line and not line.startswith('#'):
                segments.append(line)
        # A master playlist contains variants, not measured media segments.
        if not durations or len(segments) != len(durations):
            return None
        duration = sum(durations)
        if not math.isfinite(duration):
            return None
        tail = hashlib.sha256(segments[-1].encode()).hexdigest()[:20]
        return {'media_sequence': sequence, 'segment_count': len(segments),
                'duration_seconds': round(duration, 3), 'endlist': endlist,
                'playlist_type': playlist_type, 'last_segment_fingerprint': tail,
                'program_end_timestamp': (program_time + duration - program_offset
                                          if program_time is not None else None)}
    except (ValueError, OverflowError):
        return None


class SourceObservations:
    def __init__(self):
        self.rows = OrderedDict()
        self.file_responses = OrderedDict()
        self.player_history = OrderedDict()
        self.pages = set()
        self.tasks = set()

    def remember(self, *, url: str, frame_url: str, summary: dict, observed_at: float):
        key = hashlib.sha256((frame_url + '\n' + url).encode()).hexdigest()[:24]
        previous = self.rows.get(key, {})
        advanced = False
        if previous and not summary['endlist'] and not previous['endlist']:
            old_sequence, new_sequence = previous['media_sequence'], summary['media_sequence']
            advanced = ((old_sequence is not None and new_sequence is not None
                         and new_sequence > old_sequence)
                        or (summary['segment_count'] > previous['segment_count']
                            and summary['last_segment_fingerprint'] != previous['last_segment_fingerprint']))
        self.rows[key] = {**summary, 'frame_url': frame_url, 'observed_at': observed_at,
                          'last_advanced_at': observed_at if advanced else previous.get('last_advanced_at'),
                          'media_source_fingerprint': media_source_descriptor(url)['media_source_fingerprint'],
                          'source_fingerprint': key}
        self.rows.move_to_end(key)
        while len(self.rows) > 24:
            self.rows.popitem(last=False)

    def remember_file(self, *, url: str, frame_url: str, content_type: str, observed_at: float):
        """Headers only; never read audio/video bytes or launch another fetch."""
        mime = content_type.split(';', 1)[0].strip().lower()
        if mime not in {'video/mp4', 'audio/mp4', 'audio/mpeg', 'video/webm', 'audio/ogg', 'audio/wav'}:
            return
        fingerprint = media_source_descriptor(url)['media_source_fingerprint']
        self.file_responses[fingerprint] = {'frame_url': frame_url, 'observed_at': observed_at,
                                            'content_type': mime}
        self.file_responses.move_to_end(fingerprint)
        while len(self.file_responses) > 24:
            self.file_responses.popitem(last=False)

    def assessment(self, agent, page_url: str, samples: list[dict], *, waiting: bool,
                   now: float | None = None, event_ended_evidence: str | None = None) -> dict:
        now = time.time() if now is None else now
        proof = getattr(agent, 'live_target_proof', None) or {}
        target_date = getattr(agent, 'target_date', None)
        target = str(proof.get('target_url') or '')
        try:
            observed = datetime.fromisoformat(str(proof['observed_at']).replace('Z', '+00:00'))
            original = datetime.fromisoformat(str(proof.get('source_observed_at') or proof['observed_at']).replace('Z', '+00:00'))
            fresh_proof = all(value.tzinfo is not None and 0 <= now - value.timestamp() <= 21600
                              for value in (observed, original))
        except (ValueError, KeyError, TypeError, OverflowError):
            fresh_proof = False
        verified = (getattr(agent, 'live_target_identity_confirmed', False)
                    and proof.get('verified') is True
                    and proof.get('call_ticker') == agent.ticker
                    and proof.get('target_date') == str(target_date)
                    and fresh_proof and bool(target_date)
                    and bool(target) and same_event_route(target, page_url))
        result = {'version': 2, 'target_identity_verified': bool(verified),
                  'source_page_url': _public_event_url(page_url),
                  'source_target_url': _public_event_url(target),
                  'source_page_fingerprint': hashlib.sha256(page_url.encode()).hexdigest()[:24],
                  'source_target_fingerprint': hashlib.sha256(target.encode()).hexdigest()[:24],
                  'source_phase': 'identity_unverified', 'live_success_verified': False,
                  'live_success_verification_scope': 'status_report_requires_audio_speech_and_database',
                  'speech_content_verified': False, 'capture_action': 'continue_observing',
                  'playlist_evidence': [], 'active_player_count': 0,
                  'audible_player_count': 0,
                  'player_source_link_verified': False,
                  'transport_recent_wall_clock': False, 'any_player_near_edge': False,
                  'live_delivery_verified': False, 'replay_verified': False,
                  'replay_reason': None, 'ended_recording_observed': False,
                  'player_sources': [], 'source_binding_reason': 'target_identity_unverified',
                  'identity_reason': 'verified' if verified else
                      'proof_missing_or_stale' if not fresh_proof else 'target_route_or_identity_mismatch'}
        if not verified:
            return result
        matched = [row for row in samples
                   if same_event_route(target, str(row.get('frame_url') or ''))]
        active = [row for row in matched
                  if not row.get('paused') and not row.get('ended')
                  and row.get('ready_state', 0) >= 2
                  and same_event_route(target, str(row.get('frame_url') or ''))]
        result['active_player_count'] = len(active)
        # The sink records the browser's aggregate audio, including other-event
        # frames. Even a correctly bound live player cannot identify the speech
        # in that mix when another unmuted player is active.
        audible = [row for row in samples if not row.get('paused') and not row.get('ended')
                   and row.get('ready_state', 0) >= 2 and not row.get('muted')
                   and row.get('volume', 0) > 0]
        result['audible_player_count'] = len(audible)
        current = [row for row in self.rows.values()
                   if 0 <= now - row['observed_at'] <= 120
                   and same_event_route(target, row['frame_url'])]
        # HTTP updates are transport evidence. They are not evidence of speech
        # or proof that the playing media is the same request (e.g. an ad).
        dynamic = [row for row in current if not row['endlist']
                   and row['playlist_type'] != 'VOD' and row.get('last_advanced_at') is not None
                   and 0 <= now - row['last_advanced_at'] <= 60]
        finalized = [row for row in current if row['endlist'] and row['duration_seconds'] >= 600]
        phase = ('waiting_for_start' if waiting else 'live_transport_observed' if dynamic
                 else 'replay_candidate' if finalized and any(
                     isinstance(row.get('duration_seconds'), (int, float))
                     and row['duration_seconds'] >= 600 for row in active)
                 else 'unconfirmed')
        # Publish this separate from the phase; live transport can coexist with
        # a player that is paused, unobservable, or playing from a DVR archive.
        recent_wall_clock = any(row.get('program_end_timestamp') is not None
                                and -30 <= now - row['program_end_timestamp'] <= 120
                                for row in dynamic)
        at_edge = any(isinstance(row.get('seekable_end'), (int, float))
                      and row['seekable_end'] > 0
                      and 0 <= row['seekable_end'] - row.get('current_time', 0) <= 30
                      for row in active)
        # Bind only an exact currentSrc to an observed media playlist. A blob
        # MediaSource is deliberately unbound: a same-frame fetch could be an ad.
        bound = []
        files = []
        for sample in matched:
            fingerprint = sample.get('media_source_fingerprint')
            selected_http = bool(fingerprint and sample.get('media_source_is_http'))
            links = [row for row in current if selected_http
                     and row.get('media_source_fingerprint') == fingerprint]
            response = self.file_responses.get(fingerprint, {})
            response_file = bool(response and 0 <= now-response['observed_at'] <= 120
                                 and same_event_route(target, response['frame_url']))
            file_source = selected_http and (sample.get('media_source_kind') == 'file' or response_file)
            if links:
                bound.extend((sample, row) for row in links)
            if file_source:
                files.append(sample)
            if fingerprint:
                result['player_sources'].append({key: sample.get(key) for key in (
                    'media_source_fingerprint', 'media_source_kind', 'ended', 'duration_seconds',
                    'current_time', 'seekable_end', 'recording_status')})
        result['player_sources'] = result['player_sources'][:8]
        result['player_source_link_verified'] = bool(bound or files)
        result['source_binding_reason'] = ('exact_current_source' if bound or files else
            'blob_source_unmapped' if any(row.get('media_source_kind') == 'blob' for row in matched)
            else 'no_exact_player_source_match')
        live_bound = [(sample, row) for sample, row in bound if sample in active and row in dynamic]
        # A native selected HLS source plus fresh wall time, advancing playlist
        # and the *same* audible advancing player at its edge is live delivery.
        # This does not establish intelligible earnings speech or full coverage.
        delivery = False
        for sample, row in live_bound:
            fingerprint = sample.get('media_source_fingerprint')
            key = (str(sample.get('key') or sample.get('index') or ''), fingerprint)
            previous = self.player_history.get(key)
            current_time = sample.get('current_time')
            edge = sample.get('seekable_end')
            progressing = bool(previous and 0 < now-previous[0] <= 120
                               and isinstance(current_time, (float, int))
                               and current_time > previous[1] + .05)
            if isinstance(current_time, (float, int)) and math.isfinite(current_time):
                self.player_history[key] = (now, current_time)
                self.player_history.move_to_end(key)
            wall = row.get('program_end_timestamp')
            delivery = delivery or bool(len(audible) == 1 and sample is audible[0]
                and progressing and not sample.get('muted')
                and sample.get('volume', 0) > 0
                and isinstance(edge, (int, float)) and isinstance(current_time, (int, float))
                and 0 <= edge-current_time <= 30
                and wall is not None and -30 <= now-wall <= 120)
        while len(self.player_history) > 24:
            self.player_history.popitem(last=False)
        fixed_players = [sample for sample in files if
            isinstance(sample.get('duration_seconds'), (int, float))
            and sample['duration_seconds'] >= 600]
        fixed_players += [sample for sample, row in bound if row['endlist']
            and row['duration_seconds'] >= 600]
        result['ended_recording_observed'] = bool(not waiting and any(
            sample.get('ended') for sample in fixed_players))
        explicit_replay = [sample for sample in fixed_players if
            sample.get('recording_status') in {'ended', 'replay', 'on-demand', 'archived'}
            or (event_ended_evidence and sample.get('ended'))]
        # A finished ad or old player beside a live/unmapped active player must
        # not close the whole route. Ambiguity leaves admission unchanged.
        other_active = [sample for sample in active if sample not in explicit_replay]
        if not waiting and explicit_replay and not other_active:
            result.update(replay_verified=True, replay_reason='bound_recording_with_event_status',
                          capture_action='reject_replay_route')
            phase = 'ended_replay_verified'
        elif not waiting and delivery:
            result['live_delivery_verified'] = True
            phase = 'live_delivery_verified'
        elif not waiting and fixed_players and not dynamic:
            phase = 'replay_candidate'
        result.update(source_phase=phase, transport_recent_wall_clock=recent_wall_clock,
                      any_player_near_edge=at_edge)
        result['playlist_evidence'] = [{key: value for key, value in row.items() if key != 'frame_url'}
                                       for row in current[-4:]]
        return result


def attach_source_observer(agent, page) -> None:
    if getattr(agent, 'lifecycle', None) != 'live':
        return
    observer = getattr(agent, '_source_observations', None)
    if observer is None:
        observer = agent._source_observations = SourceObservations()
    if id(page) in observer.pages:
        return
    observer.pages.add(id(page))

    async def inspect(response):
        try:
            # Read only already fetched, bounded text responses. No explicit
            # fetch, manifest refresh, or access-control workaround is used.
            frame_url = str(response.request.frame.url)
            headers = response.headers
            size = int(headers.get('content-length', '0'))
            if (not 0 < size <= MAX_PLAYLIST_BYTES or not 200 <= response.status < 300
                    or headers.get('content-encoding', 'identity').lower() != 'identity'):
                return
            body = await asyncio.wait_for(response.text(), timeout=2)
            summary = playlist_summary(body)
            if summary:
                observer.remember(url=response.url, frame_url=frame_url,
                                  summary=summary, observed_at=time.time())
        except Exception:
            return

    def on_response(response):
        try:
            headers = response.headers
            content_type = headers.get('content-type', '').lower()
            if 200 <= response.status < 300:
                observer.remember_file(url=response.url, frame_url=str(response.request.frame.url),
                                       content_type=content_type, observed_at=time.time())
            if (not urlsplit(response.url).path.lower().endswith('.m3u8')
                    and 'mpegurl' not in content_type):
                return
            if len(observer.tasks) >= 2:
                return
            task = asyncio.create_task(inspect(response))
            observer.tasks.add(task)
            task.add_done_callback(observer.tasks.discard)
        except Exception:
            return
    page.on('response', on_response)


def record_source_observation(agent, page_url: str, samples: list[dict], *, waiting: bool,
                              event_ended_evidence: str | None = None) -> None:
    try:
        observer = getattr(agent, '_source_observations', None) or SourceObservations()
        assessment = observer.assessment(agent, page_url, samples, waiting=waiting,
                                         event_ended_evidence=event_ended_evidence)
        emit_live_event('capture_source', 'source_observation', status=assessment['source_phase'],
                        **assessment)
    except Exception:
        # Diagnostics must never stop the audio supervisor.
        return


def summarize_live_verification(call: dict, progress: dict, transcript: dict, *, now=None) -> dict:
    source = progress.get('capture_source') or {}
    now = time.time() if now is None else now
    same_session = (str(source.get('capture_session_id') or '') == str(call.get('capture_session_id') or '')
                    and bool(call.get('capture_session_id'))
                    and str(source.get('schedule_revision')) == str(call.get('schedule_revision'))
                    and str(source.get('call_id')) == str(call.get('id'))
                    and source.get('ticker') == call.get('ticker'))
    try:
        parsed = datetime.fromisoformat(str(source['timestamp_utc']).replace('Z', '+00:00'))
        age = now - parsed.timestamp() if parsed.tzinfo is not None else float('inf')
        fresh = 0 <= age <= 120
    except (ValueError, KeyError, TypeError, OverflowError):
        fresh = False
    # Finished attempts retain useful historical evidence; never describe an old
    # snapshot as the source that is currently playing.
    phase = source.get('source_phase', 'unconfirmed') if same_session and fresh else 'unconfirmed'
    def aligned(record: dict) -> bool:
        try:
            stamp = datetime.fromisoformat(str(record['timestamp_utc']).replace('Z', '+00:00'))
            return bool(stamp.tzinfo is not None and 0 <= now-stamp.timestamp() <= 45
                        and str(record.get('capture_session_id')) == str(call.get('capture_session_id'))
                        and str(record.get('schedule_revision')) == str(call.get('schedule_revision'))
                        and str(record.get('call_id')) == str(call.get('id'))
                        and record.get('ticker') == call.get('ticker'))
        except (KeyError, ValueError, TypeError, OverflowError):
            return False
    audio, speech, archive = (progress.get(name) or {} for name in ('audio', 'stt', 'archive'))
    delivery = bool(same_session and fresh and aligned(source)
                    and source.get('target_identity_verified') is True
                    and source.get('live_delivery_verified') is True
                    and source.get('player_source_link_verified') is True
                    and source.get('source_phase') == 'live_delivery_verified')
    speech_age = speech.get('last_speech_age_seconds')
    speech_now = bool(aligned(speech) and speech.get('speech_seen') is True
                      and speech.get('speech_evidence_reason') == 'speech_continuity'
                      and isinstance(speech_age, (int, float)) and 0 <= speech_age <= 30)
    audible = bool(aligned(audio) and audio.get('audio_condition') == 'signal_present')
    saved = bool(aligned(archive) and archive.get('event') == 'segment_db_committed'
                 and archive.get('status') == 'saved'
                 and int(archive.get('db_committed_sequence') or 0) > 0
                 and int(transcript.get('stored_rows') or 0) > 0)
    verified = bool(delivery and speech_now and audible and saved
                    and call.get('status') in {'live', 'running'})
    minimum = ('verified_live_audio_transcribed' if verified else
               'requires_source_and_speech_review' if transcript.get('stored_rows') else
               'awaiting_text' if call.get('status') in {'upcoming', 'live', 'running'} else
               'not_met_no_text')
    return {'source_phase': phase,
            'last_observed_source_phase': source.get('source_phase') if same_session else None,
            'source_observed_at': source.get('timestamp_utc') if same_session else None,
            'source_evidence_fresh': bool(same_session and fresh),
            'target_identity_verified': bool(same_session and fresh and source.get('target_identity_verified')),
            'live_delivery_verified': delivery,
            'live_success_verified': verified,
            'speech_observed': speech_now,
            'durable_text_verified': saved,
            'audible_source_observed': audible,
            'coverage_verification': 'not_assessed',
            'transcript_accuracy_verification': 'not_assessed',
            'replay_verified': bool(same_session and fresh and source.get('replay_verified') is True),
            'verification_meaning': 'current_event_live_delivery_audible_speech_and_saved_text',
            'stored_transcript_rows': int(transcript.get('stored_rows') or 0),
            'minimum_live_success': minimum,
            'note': 'Verification does not establish transcript accuracy, speaker identity or complete coverage; '
                    'text count alone never establishes live delivery.'}
