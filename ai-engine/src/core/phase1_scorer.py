"""Low-latency phase-1 raw scoring with FinBERT as the primary local model."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional runtime dependency
    import torch
except ImportError:  # pragma: no cover - optional runtime dependency
    torch = None

try:  # pragma: no cover - optional runtime dependency
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except ImportError:  # pragma: no cover - optional runtime dependency
    AutoModelForSequenceClassification = None
    AutoTokenizer = None


POSITIVE_WORDS = {
    "beat", "beats", "exceeded", "raised", "growth", "strong", "record", "improved",
    "expansion", "accelerated", "upside", "profitability", "momentum", "demand",
}
NEGATIVE_WORDS = {
    "miss", "missed", "cut", "lowered", "weak", "decline", "delayed", "pressure",
    "headwind", "soft", "downside", "loss", "slower", "uncertain", "constrained",
}


@dataclass(frozen=True)
class Phase1ScoreResult:
    raw_score: float
    confidence: float
    provider: str
    rationale_hint: str


class Phase1Scorer:
    """Fast phase-1 scorer aligned with the raw_score-first backend contract.

    Primary path:
    - Local FinBERT inference

    Reliability path:
    - Lexical fallback when model dependencies or inference are unavailable
    """

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._init_lock = threading.RLock()
        self._cache_lock = threading.RLock()
        self._cache: OrderedDict[str, Phase1ScoreResult] = OrderedDict()
        self._init_error: Optional[str] = None

    def analyze_text(self, text: str) -> Phase1ScoreResult:
        settings = get_settings()
        clipped = (text or "").strip()[: settings.phase1_max_chars]
        cache_key = " ".join(clipped.lower().split())

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result: Optional[Phase1ScoreResult] = None
        if settings.phase1_provider == "finbert":
            result = self._analyze_with_finbert(clipped)

        if result is None:
            result = self._analyze_with_lexical(clipped)

        self._remember(cache_key, result)
        return result

    def warmup(self) -> None:
        """Optionally initialize the phase-1 model during app startup."""

        settings = get_settings()
        if settings.phase1_provider != "finbert":
            return
        _ = self._ensure_finbert_loaded()

    def status_snapshot(self) -> dict[str, object]:
        """Expose lightweight operational state for monitoring."""

        with self._cache_lock:
            cache_size = len(self._cache)

        return {
            "provider": "finbert" if self._model is not None else "lexical_fallback",
            "finbert_loaded": self._model is not None and self._tokenizer is not None,
            "device": self._device,
            "cache_size": cache_size,
            "init_error": self._init_error,
        }

    def _analyze_with_finbert(self, text: str) -> Optional[Phase1ScoreResult]:
        loaded = self._ensure_finbert_loaded()
        if not loaded or self._model is None or self._tokenizer is None or torch is None:
            return None

        settings = get_settings()
        try:
            encoded = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=settings.phase1_finbert_max_length,
                padding=False,
            )
            if self._device == "cuda":
                encoded = {key: value.to("cuda") for key, value in encoded.items()}

            with torch.inference_mode():
                outputs = self._model(**encoded)
                probabilities = torch.softmax(outputs.logits[0], dim=-1).detach().cpu().tolist()

            raw_score, confidence = _score_from_probabilities(probabilities, self._model.config.id2label)
            return Phase1ScoreResult(
                raw_score=raw_score,
                confidence=confidence,
                provider="finbert_phase1",
                rationale_hint=_hint_from_score(raw_score),
            )
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            logger.warning("FinBERT inference failed, switching to lexical fallback: %s", exc)
            return None

    def _analyze_with_lexical(self, text: str) -> Phase1ScoreResult:
        normalized = (text or "").lower()
        pos_hits = sum(1 for token in POSITIVE_WORDS if token in normalized)
        neg_hits = sum(1 for token in NEGATIVE_WORDS if token in normalized)
        total = pos_hits + neg_hits

        if total == 0:
            return Phase1ScoreResult(
                raw_score=0.0,
                confidence=0.35,
                provider="lexical_phase1",
                rationale_hint="Material directional language was limited in this chunk.",
            )

        raw_score = (pos_hits - neg_hits) / max(total, 1)
        confidence = min(0.9, 0.35 + total * 0.1)
        return Phase1ScoreResult(
            raw_score=round(max(-1.0, min(1.0, raw_score)), 4),
            confidence=round(confidence, 4),
            provider="lexical_phase1",
            rationale_hint=_hint_from_score(raw_score),
        )

    def _ensure_finbert_loaded(self) -> bool:
        if self._model is not None and self._tokenizer is not None:
            return True

        with self._init_lock:
            if self._model is not None and self._tokenizer is not None:
                return True

            if AutoTokenizer is None or AutoModelForSequenceClassification is None or torch is None:
                self._init_error = "transformers/torch not installed"
                logger.info("FinBERT dependencies are unavailable; lexical fallback will be used")
                return False

            settings = get_settings()
            try:
                model_name = settings.phase1_finbert_model_name
                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
                if not _has_valid_label_schema(self._model.config.id2label):
                    raise ValueError(
                        "phase1 FinBERT model must expose POSITIVE and NEGATIVE labels"
                    )
                self._device = _resolve_device(settings.phase1_finbert_device)
                if self._device == "cuda":
                    self._model.to("cuda")
                self._model.eval()
                logger.info("Phase-1 FinBERT loaded: model=%s device=%s", model_name, self._device)
                self._init_error = None
                return True
            except Exception as exc:  # pragma: no cover - model download/runtime dependent
                self._init_error = str(exc)
                logger.warning("FinBERT initialization failed; lexical fallback will be used: %s", exc)
                self._model = None
                self._tokenizer = None
                return False

    def _get_cached(self, key: str) -> Optional[Phase1ScoreResult]:
        with self._cache_lock:
            result = self._cache.get(key)
            if result is None:
                return None
            self._cache.move_to_end(key)
            return result

    def _remember(self, key: str, value: Phase1ScoreResult) -> None:
        settings = get_settings()
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > settings.phase1_cache_size:
                self._cache.popitem(last=False)


def fallback_gemini_result(text: str, phase1_result: Phase1ScoreResult):
    """Create a Gemini-shaped result when the richer LLM stage is unavailable."""

    from ..models.signal_models import GeminiAnalysisResult

    direction = "NEUTRAL"
    catalyst = "MACRO_COMMENTARY"
    if phase1_result.raw_score > 0.05:
        direction = "BULLISH"
        catalyst = "EARNINGS_BEAT"
    elif phase1_result.raw_score < -0.05:
        direction = "BEARISH"
        catalyst = "EARNINGS_MISS"

    return GeminiAnalysisResult(
        direction=direction,
        magnitude=abs(phase1_result.raw_score),
        confidence=max(phase1_result.confidence, 0.35),
        rationale=f"{phase1_result.rationale_hint} Phase-1 provider={phase1_result.provider}.",
        catalyst_type=catalyst,
        euphemism_count=0,
        negative_word_ratio=max(0.0, -phase1_result.raw_score),
        cot_reasoning="Fallback rationale generated from the phase-1 raw-score stage.",
        model_route=f"fallback:{phase1_result.provider}",
    )


def blend_raw_scores(*, phase1_score: float, llm_score: float, llm_available: bool) -> float:
    """Prefer the phase-1 contract score but stabilize it with the richer LLM pass when available."""

    if not llm_available:
        return round(max(-1.0, min(1.0, phase1_score)), 4)

    if phase1_score == 0.0:
        return round(max(-1.0, min(1.0, llm_score)), 4)

    same_sign = (phase1_score >= 0 and llm_score >= 0) or (phase1_score <= 0 and llm_score <= 0)
    if same_sign:
        blended = phase1_score * 0.6 + llm_score * 0.4
    else:
        blended = phase1_score * 0.8 + llm_score * 0.2
    return round(max(-1.0, min(1.0, blended)), 4)


def _resolve_device(device_setting: str) -> str:
    if device_setting == "cpu":
        return "cpu"
    if device_setting == "cuda":
        return "cuda"
    if torch is not None and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _score_from_probabilities(probabilities: list[float], id2label: dict[int, str]) -> tuple[float, float]:
    label_map = {str(value).upper(): index for index, value in id2label.items()}
    if "POSITIVE" not in label_map or "NEGATIVE" not in label_map:
        raise ValueError("id2label must contain POSITIVE and NEGATIVE labels")

    positive = probabilities[label_map["POSITIVE"]]
    negative = probabilities[label_map["NEGATIVE"]]
    neutral = probabilities[label_map["NEUTRAL"]] if "NEUTRAL" in label_map else 0.0

    raw_score = round(max(-1.0, min(1.0, positive - negative)), 4)
    directional_confidence = max(positive, negative)
    confidence = round(max(directional_confidence, neutral), 4)
    return raw_score, confidence


def _has_valid_label_schema(id2label: dict[int, str]) -> bool:
    normalized = {str(value).upper() for value in id2label.values()}
    return "POSITIVE" in normalized and "NEGATIVE" in normalized


def _hint_from_score(raw_score: float) -> str:
    if raw_score > 0.15:
        return "Management language was directionally positive."
    if raw_score < -0.15:
        return "Management language was directionally negative."
    return "Management language was mixed or close to neutral."


phase1_scorer = Phase1Scorer()
