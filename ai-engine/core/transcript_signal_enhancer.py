from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import re
from typing import Deque

try:
    from models.request_models import SectionType
    from models.signal_models import GeminiAnalysisResult
except ImportError:  # pragma: no cover
    from ..models.request_models import SectionType
    from ..models.signal_models import GeminiAnalysisResult


_FILLER_PATTERNS = [
    r"\bas we said\b",
    r"\btoo early\b",
    r"\bnot going to comment\b",
    r"\bcan't comment\b",
    r"\bwe are focused on\b",
    r"\blonger[ -]term\b",
    r"\bmore to come\b",
    r"\bremains unchanged\b",
]

_CLAIM_STOPWORDS = {
    "the", "and", "for", "that", "with", "from", "have", "this", "were", "into", "about", "will",
    "would", "there", "their", "your", "they", "them", "what", "when", "where", "which", "while",
    "our", "we", "you", "are", "but", "not", "can", "could", "should", "after", "before", "more",
}

_TOPIC_LEXICONS = {
    "guidance": {
        "positive": ["raise guidance", "raising guidance", "guidance up", "above the prior range", "stronger outlook", "higher outlook", "upward revision", "reaffirmed and above"],
        "negative": ["lower guidance", "cut guidance", "guidance down", "below the prior range", "weaker outlook", "softer outlook", "downward revision"],
        "neutral": ["guidance", "outlook", "forecast", "full year"],
    },
    "capex": {
        "positive": ["capacity expansion", "investment cycle", "buildout", "increase capex", "accelerate investment"],
        "negative": ["capex constraint", "reduce capex", "capex moderation", "spending cut"],
        "neutral": ["capex", "capital expenditure", "investment", "spending"],
    },
    "margin": {
        "positive": ["gross margin expansion", "operating leverage", "margin improvement", "expand margin", "better mix"],
        "negative": ["margin pressure", "gross margin headwind", "margin compression", "promotional pressure", "mix headwind"],
        "neutral": ["margin", "gross margin", "operating margin"],
    },
    "demand": {
        "positive": ["healthy demand", "strong demand", "order strength", "backlog improved", "bookings accelerated", "demand improved"],
        "negative": ["soft demand", "demand weakness", "order slowdown", "backlog pressure", "customer digestion", "demand softened"],
        "neutral": ["demand", "orders", "bookings", "backlog", "pipeline"],
    },
}


@dataclass(frozen=True)
class TranscriptSignalSnapshot:
    evasion_score: float
    specificity_score: float
    contradiction_penalty: float
    velocity: float
    acceleration: float
    velocity_modifier: float
    acoustic_stress: float
    topic_levels: dict[str, float]
    topic_deltas: dict[str, float]
    risk_flags: list[str]

    def to_dict(self) -> dict[str, float | list[str] | dict[str, float]]:
        return {
            "evasion_score": round(self.evasion_score, 4),
            "specificity_score": round(self.specificity_score, 4),
            "contradiction_penalty": round(self.contradiction_penalty, 4),
            "velocity": round(self.velocity, 4),
            "acceleration": round(self.acceleration, 4),
            "velocity_modifier": round(self.velocity_modifier, 4),
            "acoustic_stress": round(self.acoustic_stress, 4),
            "topic_levels": {k: round(v, 4) for k, v in self.topic_levels.items()},
            "topic_deltas": {k: round(v, 4) for k, v in self.topic_deltas.items()},
            "risk_flags": list(self.risk_flags),
        }


class TranscriptSignalEnhancer:
    """Text-first signal refinements for earnings-call/Q&A transcripts.

    This intentionally avoids extra LLM calls. It extracts a few stable signals from
    transcript/STT text: directness, numerical specificity, rolling sentiment drift,
    claim-to-claim contradiction risk, and topic-shift deltas around guidance/capex/
    margin/demand language.
    """

    def __init__(self, *, window: int = 8) -> None:
        self._scores: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._prev_velocity: dict[str, float] = defaultdict(float)
        self._claims: dict[str, list[tuple[set[str], float, str]]] = defaultdict(list)
        self._topic_scores: dict[str, dict[str, Deque[float]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=window))
        )

    def evaluate(
        self,
        *,
        ticker: str,
        text_chunk: str,
        section_type: SectionType,
        analysis: GeminiAnalysisResult,
        audio_features: dict[str, float] | None = None,
    ) -> TranscriptSignalSnapshot:
        normalized_ticker = (ticker or "").upper()
        signed_score = _signed_sentiment(analysis.direction, analysis.magnitude)
        velocity, acceleration, velocity_modifier = self._update_velocity(normalized_ticker, signed_score)

        specificity_score = _specificity_score(text_chunk)
        evasion_score = _evasion_score(text_chunk, section_type, specificity_score)
        contradiction_penalty = self._contradiction_penalty(
            normalized_ticker,
            text_chunk=text_chunk,
            rationale=analysis.rationale,
            signed_score=signed_score,
        )
        acoustic_stress = _acoustic_stress(audio_features)
        topic_levels, topic_deltas = self._topic_shift_snapshot(normalized_ticker, text_chunk)

        risk_flags: list[str] = []
        if section_type == SectionType.Q_AND_A and evasion_score >= 0.58:
            risk_flags.append("qa_evasive_answer")
        if specificity_score <= 0.22:
            risk_flags.append("low_numeric_specificity")
        if contradiction_penalty <= -0.14:
            risk_flags.append("management_contradiction_risk")
        if velocity <= -0.035:
            risk_flags.append("negative_sentiment_velocity")
        if acoustic_stress >= 0.08:
            risk_flags.append("acoustic_stress_spike")
        if topic_deltas.get("guidance", 0.0) <= -0.18:
            risk_flags.append("guidance_downshift")
        if topic_deltas.get("margin", 0.0) <= -0.14:
            risk_flags.append("margin_pressure_language")
        if topic_deltas.get("demand", 0.0) <= -0.16:
            risk_flags.append("demand_softening_language")

        return TranscriptSignalSnapshot(
            evasion_score=evasion_score,
            specificity_score=specificity_score,
            contradiction_penalty=contradiction_penalty,
            velocity=velocity,
            acceleration=acceleration,
            velocity_modifier=velocity_modifier,
            acoustic_stress=acoustic_stress,
            topic_levels=topic_levels,
            topic_deltas=topic_deltas,
            risk_flags=risk_flags,
        )

    def apply(
        self,
        analysis: GeminiAnalysisResult,
        snapshot: TranscriptSignalSnapshot,
    ) -> GeminiAnalysisResult:
        if analysis.direction == "NEUTRAL":
            analysis.metadata.update({"transcript_signals": snapshot.to_dict()})
            return analysis

        confidence_penalty = min(0.22, snapshot.evasion_score * 0.10 + max(0.0, -snapshot.contradiction_penalty) * 0.18)
        analysis.confidence = _clamp(analysis.confidence - confidence_penalty)

        signed = _signed_sentiment(analysis.direction, analysis.magnitude)
        signed += snapshot.velocity_modifier + snapshot.contradiction_penalty
        if snapshot.acoustic_stress > 0.0:
            signed -= min(0.12, snapshot.acoustic_stress * 0.35)
        if snapshot.evasion_score > 0.0 and analysis.direction == "BULLISH":
            signed -= min(0.08, snapshot.evasion_score * 0.08)

        guidance_delta = snapshot.topic_deltas.get("guidance", 0.0)
        demand_delta = snapshot.topic_deltas.get("demand", 0.0)
        margin_delta = snapshot.topic_deltas.get("margin", 0.0)
        capex_delta = snapshot.topic_deltas.get("capex", 0.0)
        signed += max(-0.10, min(0.10, guidance_delta * 0.22))
        signed += max(-0.08, min(0.08, demand_delta * 0.18))
        signed += max(-0.06, min(0.06, margin_delta * 0.14))
        if capex_delta >= 0.16 and demand_delta >= 0.08:
            signed += 0.03
        elif capex_delta >= 0.16 and margin_delta <= -0.10:
            signed -= 0.03

        analysis.direction = "BULLISH" if signed > 0.05 else "BEARISH" if signed < -0.05 else "NEUTRAL"
        analysis.magnitude = _clamp(abs(signed))
        analysis.risk_flags.extend(flag for flag in snapshot.risk_flags if flag not in analysis.risk_flags)
        analysis.metadata.update({"transcript_signals": snapshot.to_dict()})
        return analysis

    def _update_velocity(self, ticker: str, signed_score: float) -> tuple[float, float, float]:
        scores = self._scores[ticker]
        scores.append(float(signed_score))
        if len(scores) < 4:
            return 0.0, 0.0, 0.0

        y = list(scores)
        n = len(y)
        x = list(range(n))
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        denom = sum((xi - mean_x) ** 2 for xi in x) or 1.0
        slope = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / denom
        acceleration = slope - self._prev_velocity[ticker]
        self._prev_velocity[ticker] = slope

        modifier = 0.0
        if slope < -0.035:
            modifier = max(-0.22, slope * 2.3)
            if acceleration < -0.02:
                modifier *= 1.2
        return float(slope), float(acceleration), float(max(-0.28, modifier))

    def _contradiction_penalty(
        self,
        ticker: str,
        *,
        text_chunk: str,
        rationale: str,
        signed_score: float,
    ) -> float:
        claim_text = _extract_claim(text_chunk, rationale)
        claim_tokens = _claim_tokens(claim_text)
        if len(claim_tokens) < 5:
            return 0.0

        penalty = 0.0
        for past_tokens, past_score, _past_text in self._claims[ticker][-12:]:
            overlap = _jaccard(claim_tokens, past_tokens)
            if overlap >= 0.38 and (signed_score * past_score) < -0.06:
                penalty = min(penalty, -0.18 - min(0.12, overlap * 0.12))
                break

        self._claims[ticker].append((claim_tokens, signed_score, claim_text))
        if len(self._claims[ticker]) > 32:
            self._claims[ticker] = self._claims[ticker][-32:]
        return float(penalty)

    def _topic_shift_snapshot(self, ticker: str, text_chunk: str) -> tuple[dict[str, float], dict[str, float]]:
        topic_levels: dict[str, float] = {}
        topic_deltas: dict[str, float] = {}
        text = text_chunk or ""
        for topic, lexicon in _TOPIC_LEXICONS.items():
            current = _topic_score(text, lexicon)
            history = self._topic_scores[ticker][topic]
            baseline = sum(history) / len(history) if history else 0.0
            delta = current - baseline
            history.append(current)
            topic_levels[topic] = current
            topic_deltas[topic] = delta
        return topic_levels, topic_deltas



def _signed_sentiment(direction: str, magnitude: float) -> float:
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0 if str(direction).upper() == "BEARISH" else 0.0
    return float(sign * _clamp(magnitude))


def _specificity_score(text: str) -> float:
    text = text or ""
    words = re.findall(r"[A-Za-z]+", text)
    word_count = max(len(words), 1)
    numeral_hits = len(re.findall(r"\b\d+(?:\.\d+)?\b|\$\d+(?:\.\d+)?|\d+%|bps|basis points", text, flags=re.I))
    time_hits = len(re.findall(r"\b(?:Q[1-4]|FY\d{2,4}|January|February|March|April|May|June|July|August|September|October|November|December)\b", text, flags=re.I))
    density = (numeral_hits + 0.5 * time_hits) / word_count
    return _clamp(density * 6.5)


def _evasion_score(text: str, section_type: SectionType, specificity_score: float) -> float:
    if section_type != SectionType.Q_AND_A:
        return 0.0
    text_l = (text or "").lower()
    filler_hits = sum(1 for pattern in _FILLER_PATTERNS if re.search(pattern, text_l))
    question_marks = text_l.count("?")
    answer_ratio_penalty = 0.0
    if question_marks >= 1:
        parts = re.split(r"\?", text_l, maxsplit=1)
        if len(parts) == 2:
            q_words = set(re.findall(r"[a-z]+", parts[0])) - _CLAIM_STOPWORDS
            a_words = set(re.findall(r"[a-z]+", parts[1])) - _CLAIM_STOPWORDS
            if q_words:
                overlap = len(q_words & a_words) / len(q_words)
                answer_ratio_penalty = max(0.0, 0.45 - overlap)
    raw = 0.18 * filler_hits + answer_ratio_penalty + max(0.0, 0.28 - specificity_score)
    return _clamp(raw)


def _extract_claim(text_chunk: str, rationale: str) -> str:
    source = (rationale or "").strip() or (text_chunk or "").strip()
    if not source:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", source)
    for sentence in sentences:
        normalized = sentence.strip()
        if len(normalized.split()) >= 8:
            return normalized
    return source[:240]


def _claim_tokens(text: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _CLAIM_STOPWORDS}
    return words


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _topic_score(text: str, lexicon: dict[str, list[str]]) -> float:
    text_l = (text or "").lower()
    positive = sum(text_l.count(term) for term in lexicon.get("positive", []))
    negative = sum(text_l.count(term) for term in lexicon.get("negative", []))
    neutral = sum(text_l.count(term) for term in lexicon.get("neutral", []))
    if positive == 0 and negative == 0 and neutral == 0:
        return 0.0
    score = (positive - negative) / max(1, positive + negative + neutral)
    return _clamp(score, -1.0, 1.0)


def _acoustic_stress(audio_features: dict[str, float] | None) -> float:
    if not audio_features:
        return 0.0
    pitch_delta = float(audio_features.get("pitch_delta", 0.0) or 0.0)
    pause_delta = float(audio_features.get("pause_ratio_delta", 0.0) or 0.0)
    rate_delta = float(audio_features.get("speaking_rate_delta", 0.0) or 0.0)
    stress = max(0.0, pitch_delta * 0.55 + pause_delta * 0.25 + rate_delta * 0.20)
    return _clamp(stress)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


__all__ = ["TranscriptSignalEnhancer", "TranscriptSignalSnapshot"]
