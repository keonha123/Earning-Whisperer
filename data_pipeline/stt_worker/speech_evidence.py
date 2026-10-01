"""Conservative speech-start evidence, separate from transcript preservation.

Whisper can produce text over waiting music. One string is therefore not enough
reason to replace the long prelive allowance with the shorter speech-idle guard.
This is a continuity heuristic, not an audio/music classifier or a text filter.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from typing import Iterable

from data_pipeline.live_end import is_non_speech_fragment


_METADATA_FIELDS = ("no_speech_prob", "avg_logprob", "compression_ratio")


def segment_evidence_payload(segment: object) -> dict:
    """Keep optional model evidence when crossing the isolated model pipe."""
    result = {"text": str(getattr(segment, "text", ""))}
    for name in _METADATA_FIELDS:
        value = getattr(segment, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[name] = float(value)
    return result


@dataclass(frozen=True)
class SpeechEvidence:
    confirmed: bool
    credible_window: bool
    candidate_windows: int
    reason: str


class SpeechEvidenceTracker:
    """Require distinct, adjacent non-noise windows before confirming speech.

    All original text remains available to the caller for archival and closing
    detection, including short speech and uncertain model output. Once confirmed,
    a short genuine utterance may refresh the idle clock; the decision never
    revokes the fact that speech started.
    """

    def __init__(self, *, maximum_gap_seconds: float = 60.0):
        self.confirmed = False
        self.candidate_windows = 0
        self.maximum_gap_seconds = maximum_gap_seconds
        self.previous_candidate_audio_seconds: float | None = None
        self.recent_fingerprints: deque[str] = deque(maxlen=6)

    def observe(self, segments: Iterable[object], *, audio_seconds: float) -> SpeechEvidence:
        accepted = []
        rejected = "no_text"
        for segment in segments:
            value = segment_evidence_payload(segment)
            text = " ".join(value["text"].split())
            if is_non_speech_fragment(text):
                if text:
                    rejected = "explicit_non_speech"
                continue
            if value.get("no_speech_prob", 0) >= 0.6:
                rejected = "model_no_speech"
                continue
            if value.get("compression_ratio", 0) > 2.4:
                rejected = "model_repetition"
                continue
            words = re.findall(r"\w+(?:['’]\w+)?", text.casefold())
            if words:
                accepted.append(" ".join(words))
        fingerprint = " ".join(accepted)
        credible = bool(fingerprint)
        if credible and fingerprint in self.recent_fingerprints:
            credible = False
            rejected = "repeated_window"
        if fingerprint:
            self.recent_fingerprints.append(fingerprint)
        if not credible:
            self.candidate_windows = 0
            self.previous_candidate_audio_seconds = None
            return SpeechEvidence(self.confirmed, False, 0, rejected)

        previous = self.previous_candidate_audio_seconds
        adjacent = (previous is not None and 0 < audio_seconds - previous <= self.maximum_gap_seconds)
        self.candidate_windows = self.candidate_windows + 1 if adjacent else 1
        self.previous_candidate_audio_seconds = audio_seconds
        self.confirmed = self.confirmed or self.candidate_windows >= 2
        return SpeechEvidence(self.confirmed, True, self.candidate_windows,
                              "speech_continuity" if self.confirmed else "awaiting_continuity")
