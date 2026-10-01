"""Explicit operator closing evidence, independent of browser/STT backends.

Silence, music, media EOF, generic thanks and the end of Q&A never prove the
end of an earnings call. This detector requires a final call/meeting closure
AND an explicit disconnect instruction, then processed post-close audio.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any

_WORDS = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
_CLOSE = re.compile(
    r"(?:^|[.!?]\s*|\bthank\s+you[,.]?\s+)"
    r"(?:this\s+(?:does\s+)?concludes?\s+"
    # A joint Q&A + call closure ends the entire event; Q&A alone does not.
    r"(?:(?:(?:the|our)\s+)?(?:q\s*&\s*a|questions?\s+and\s+answers?)"
    r"(?:\s+session)?\s+and\s+)?(?:(?:today['’]?s|our|the)\s+)?"
    r"(?:conference(?:\s+call)?|earnings\s+call|call|meeting|webcast|webinar)"
    r"|this\s+brings\s+us\s+to\s+the\s+end\s+of\s+(?:(?:today['’]?s|our|the)\s+)?"
    r"(?:conference(?:\s+call)?|earnings\s+call|call|meeting|webcast|webinar))\b"
    r"(?:\s+for\s+today)?(?=\s*(?:[.!?,;]|$|(?:and\s+)?(?:thank\s+you|you\s+(?:may|can))\b))", re.I,
)
_DISCONNECT = re.compile(
    r"\byou\s+(?:may|can)\s+(?:now\s+)?disconnect"
    r"(?:\s+your(?:\s+(?:telephone|phone))?\s+lines?"
    r"|\s+from\s+(?:the|this)\s+(?:call|conference|webcast))?"
    r"(?=\s*(?:[.!?,;]|$|(?:now|at\s+this\s+time|or\s+log\s+off)\b))", re.I,
)


def explicit_operator_close(text: str) -> bool:
    text = ' '.join(str(text or '').split())
    close = _CLOSE.search(text)
    disconnect = _DISCONNECT.search(text)
    return bool(close and disconnect and close.start() < disconnect.start()
                and disconnect.end() - close.start() <= 650)


# Full utterances only, and usable only AFTER an explicit call + disconnect
# candidate. In particular, generic thanks never starts a closing candidate.
# "Connect your lines" is the observed STT truncation of "disconnect" in a
# following JBL window, not an independent instruction proving an event end.
_CLOSING_COURTESY = (
    r"(?:we )?thank you(?: very much)?"
    r"(?: for (?:your )?(?:time(?: and participation)?|participation|attending|"
    r"joining(?: us)?|listening)(?: today)?)?"
    r"|(?:have|enjoy) (?:(?:a |the rest of your )(?:good |great |wonderful |nice )?day"
    r"|a (?:good |great |wonderful |nice )?(?:evening|weekend))"
)
_CLOSING_EXIT_INSTRUCTION = (
    r"(?:you (?:may|can) (?:now )?)?(?:disconnect|connect) your (?:lines?|phones?)"
    r"(?: or log off (?:the )?(?:webcast|webinar))?(?: at this time)?"
    r"|(?:you (?:may|can) (?:now )?)?log off (?:the )?(?:webcast|webinar)(?: at this time)?"
    r"|you (?:may|can) (?:now )?disconnect(?: at this time)?"
)
_CLOSING_FOLLOWUP_CLAUSE = rf"(?:{_CLOSING_COURTESY}|{_CLOSING_EXIT_INSTRUCTION})"
_CLOSING_FOLLOWUP = re.compile(
    rf"(?:and )?{_CLOSING_FOLLOWUP_CLAUSE}(?: (?:and )?{_CLOSING_FOLLOWUP_CLAUSE})*",
    re.I,
)


def is_operator_closing_followup(text: str) -> bool:
    """Recognize only bounded, wholly closing-related speech after a candidate.

    This is still speech: it restarts the required processed-audio quiet period.
    Financial remarks, a new question, or an instruction to hold cancel instead.
    """
    normalized = re.sub(r"[^a-z0-9']+", " ", str(text or "").casefold()).strip()
    return bool(normalized and len(normalized) <= 400 and _CLOSING_FOLLOWUP.fullmatch(normalized))


def is_non_speech_fragment(text: str) -> bool:
    normalized = ' '.join(str(text or '').split()).casefold()
    # Do not suppress short real speech ("Please hold", "Another question?").
    # BORNAN BOR is the exact post-call music artifact observed in PAYX.
    return (not normalized or normalized in {'[music]', '(music)', '[applause]', '[silence]'}
            or normalized.rstrip('.!?') == 'bornan bor')


class TranscriptEndObserver:
    """Measure confirmation using processed audio, not elapsed wall time.

    A frozen STT worker or growing backlog cannot confirm an ending. A new
    substantive utterance cancels the candidate; known non-speech artifacts such as
    the observed 'BORNAN BOR.' do not extend the session indefinitely.
    """
    def __init__(self, *, settle_seconds: float = 60, minimum_speech_windows: int = 12,
                 minimum_audio_seconds: float = 120):
        self.settle_seconds = max(60, float(settle_seconds))
        self.minimum_speech_windows = max(2, int(minimum_speech_windows))
        self.minimum_audio_seconds = max(30, float(minimum_audio_seconds))
        self.recent: deque[tuple[float, str]] = deque(maxlen=4)
        self.speech_windows = 0
        self.candidate: dict[str, Any] | None = None
        self.quiet_windows = 0
        self.last_audio_seconds = 0.0

    def observe(self, text: str, *, audio_seconds: float, backlog_seconds: float) -> dict | None:
        text = ' '.join(str(text or '').split())
        words = _WORDS.findall(text)
        # Only newly processed audio advances confirmation. Repeated progress
        # snapshots or a malformed clock must not manufacture quiet windows.
        if not math.isfinite(audio_seconds) or audio_seconds <= self.last_audio_seconds:
            return None
        self.last_audio_seconds = audio_seconds
        if len(words) >= 4:
            self.speech_windows += 1
        if self.candidate:
            if is_non_speech_fragment(text):
                self.quiet_windows += 1
            elif is_operator_closing_followup(text):
                # Operator instructions often straddle model windows. Keep
                # the original full proof, but settle AFTER the last followup.
                self.candidate['closing_audio_seconds'] = audio_seconds
                self.candidate['closing_followup'] = text[-400:]
                self.quiet_windows = 0
            else:
                self.candidate = None
                self.quiet_windows = 0
                self.recent.clear()
        self.recent.append((audio_seconds, text))
        combined = ' '.join(value for stamp, value in self.recent
                            if audio_seconds - stamp <= 65 and value)
        if (self.candidate is None and text and explicit_operator_close(combined)
                and self.speech_windows >= self.minimum_speech_windows
                and audio_seconds >= self.minimum_audio_seconds):
            self.candidate = {'kind': 'operator_closing', 'text': combined[-1000:],
                              'closing_audio_seconds': audio_seconds}
            self.quiet_windows = 0
        if (self.candidate and self.quiet_windows >= 2
                and audio_seconds - self.candidate['closing_audio_seconds'] >= self.settle_seconds
                and math.isfinite(backlog_seconds) and 0 <= backlog_seconds <= 15):
            return {**self.candidate,
                    'post_close_audio_seconds': round(audio_seconds - self.candidate['closing_audio_seconds'], 3),
                    'quiet_windows': self.quiet_windows,
                    'speech_windows': self.speech_windows}
        return None


def write_bound_target_proof(path: Path, proof: dict | None, *, validated_url: str | None = None) -> None:
    """Companion to the existing readiness flag; same run and event only."""
    if not isinstance(proof, dict) or proof.get('verified') is not True:
        return
    from .live_runtime import atomic_json
    atomic_json(Path(str(path) + '.proof.json'), {
        'version': 1, 'run_id': os.getenv('WEBCAST_LIVE_RUN_ID', ''),
        'call_id': os.getenv('CALL_ID', ''),
        'capture_session_id': os.getenv('STT_CAPTURE_SESSION_ID', os.getenv('CALL_ID', '')),
        'created_at': time.time(), 'proof': proof,
        'validated_url': validated_url or proof.get('target_url'),
    })


def load_bound_target_proof(config: Any) -> dict | None:
    if not (config.live_capture and config.supervised_live and config.target_identity_verified
            and config.live_run_id and config.target_event_date):
        return None
    ready = os.getenv('WEBCAST_TARGET_IDENTITY_READY_FILE', '').strip()
    active = os.getenv('WEBCAST_ACTIVE_PLAYER_URL_FILE', '').strip()
    if not ready or not active:
        return None
    try:
        path = Path(ready + '.proof.json')
        if path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            return None
        proof = value.get('proof') or {}
        if not isinstance(proof, dict):
            return None
        created = float(value.get('created_at', 0))
        observed = datetime.fromisoformat(str(proof['observed_at'])).timestamp()
        now = time.time()
        if (value.get('version') != 1 or value.get('run_id') != config.live_run_id
                or value.get('call_id') != config.call_id
                or value.get('capture_session_id') != (config.capture_session_id or config.call_id)
                or not config.live_run_started_at - 1 <= created <= now + 5
                or not 0 <= now - observed <= 21600
                or proof.get('verified') is not True
                or proof.get('call_ticker') != config.ticker
                or proof.get('target_date') != config.target_event_date):
            return None
        url = Path(active).read_text().strip()
        from .collectors.streams.browser.navigation import same_event_route
        if not same_event_route(str(value.get('validated_url') or proof.get('target_url') or ''), url):
            return None
        return {'proof': proof, 'url': url}
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None


def publish_operator_end(config: Any, evidence: dict) -> dict | None:
    """Write the existing supervisor signal; normal drain/DB checks still run."""
    bound = load_bound_target_proof(config)
    if not bound or not explicit_operator_close(str(evidence.get('text') or '')):
        return None
    if float(evidence.get('post_close_audio_seconds', 0)) < 60:
        return None
    # write_termination binds via the shell's inherited run environment. Check
    # it agrees with config before allowing that shared single-writer protocol.
    if (os.getenv('WEBCAST_LIVE_RUN_ID') != config.live_run_id
            or os.getenv('CALL_ID') != config.call_id
            or os.getenv('WEBCAST_LIVE_TERMINATION_FILE') != config.live_termination_file):
        return None
    from .collectors.streams.browser.lifetime import write_termination
    return write_termination('event_ended', verified=True, url=bound['url'],
                             proof=bound['proof'], evidence='operator_closing: ' + evidence['text'])
