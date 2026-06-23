from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import importlib
import logging
import re
import threading
from typing import Any

try:
    from config import Settings, get_settings
    from models.request_models import MarketData, SectionType, SourceType
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings
    from ..models.request_models import MarketData, SectionType, SourceType

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Phase1ScoreResult:
    raw_score: float
    confidence: float
    label: str = "neutral"
    provider: str = "heuristic"
    rationale_hint: str = ""
    heuristic_score: float = 0.0
    finbert_score: float | None = None
    finbert_confidence: float | None = None
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class FinBertScore:
    score: float
    confidence: float
    label: str


_POSITIVE_PATTERNS = [
    r"\bbeat(?:s|ing)?\b",
    r"\b(?:exceed(?:ed|s)?|above) (?:expectations|guidance|consensus)\b",
    r"\b(?:raised|raise|increased|increasing) guidance\b",
    r"\baccelerat(?:e|ed|ing|ion)\b",
    r"\b(?:margin|margins) (?:expanded|improved|increased)\b",
    r"\bstrong demand\b",
    r"\b(?:record|robust) (?:revenue|bookings|demand|backlog)\b",
    r"\bbacklog (?:grew|increased|expanded)\b",
    r"\bupside\b",
    r"\bresilien(?:t|ce)\b",
]
_NEGATIVE_PATTERNS = [
    r"\bmiss(?:ed|es|ing)?\b",
    r"\b(?:cut|lowered|reduced|withdrew) guidance\b",
    r"\bslow(?:ed|ing|down)?\b",
    r"\bsoft(?:er)? demand\b",
    r"\bheadwind(?:s)?\b",
    r"\bweaker\b",
    r"\b(?:margin|margins) (?:contracted|compressed|declined)\b",
    r"\b(?:revenue|bookings|demand|backlog) (?:declined|fell|decreased)\b",
    r"\bdelay(?:ed|s)?\b",
    r"\buncertain(?:ty)?\b",
    r"\belevated (?:costs|expenses|churn)\b",
]
_NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b|\d+%|bps|basis points", flags=re.I)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _direction(value: float, threshold: float = 0.05) -> int:
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _label_for_score(score: float) -> str:
    magnitude = abs(score)
    if magnitude >= 0.65:
        return "pass"
    if magnitude >= 0.30:
        return "review"
    return "drop"


def _score_heuristic(
    *,
    current_chunk: str,
    market_data: MarketData,
    section_type: SectionType,
    source_type: SourceType,
) -> Phase1ScoreResult:
    text = (current_chunk or "").lower()
    positive_hits = sum(1 for pattern in _POSITIVE_PATTERNS if re.search(pattern, text))
    negative_hits = sum(1 for pattern in _NEGATIVE_PATTERNS if re.search(pattern, text))
    numeric_hits = len(_NUMERIC_PATTERN.findall(text))

    text_score = _clamp((positive_hits - negative_hits) / 2.0)
    surprise_score = _clamp(float(market_data.surprise_pct or 0.0) / 10.0)
    price_confirmation = _clamp(
        (
            float(market_data.gap_pct or 0.0)
            + float(market_data.day1_return_pct or 0.0)
            + float(market_data.post_earnings_drift_pct or 0.0)
        )
        / 18.0
    )
    volume_conviction = _clamp((float(market_data.volume_ratio or 1.0) - 1.0) / 2.0, 0.0, 1.0)

    raw_score = 0.65 * text_score + 0.25 * surprise_score + 0.10 * price_confirmation
    raw_score *= 1.0 + 0.15 * volume_conviction
    if section_type == SectionType.Q_AND_A:
        raw_score *= 0.90
    if source_type == SourceType.NEWS:
        raw_score *= 1.03
    raw_score = _clamp(raw_score)

    confidence = 0.40
    confidence += min(0.24, (positive_hits + negative_hits) * 0.08)
    confidence += min(0.12, numeric_hits * 0.03)
    confidence += volume_conviction * 0.07
    confidence += min(0.10, abs(float(market_data.surprise_pct or 0.0)) * 0.01)
    confidence = _clamp(confidence, 0.0, 0.92)

    rationale_hint = (
        f"heuristic={raw_score:.4f}; positive={positive_hits}; negative={negative_hits}; "
        f"numeric={numeric_hits}; surprise={surprise_score:.4f}; volume={volume_conviction:.4f}"
    )
    return Phase1ScoreResult(
        raw_score=round(raw_score, 4),
        confidence=round(confidence, 4),
        label=_label_for_score(raw_score),
        provider="heuristic",
        rationale_hint=rationale_hint,
        heuristic_score=round(raw_score, 4),
    )


class FinBertSentimentAdapter:
    """Lazy local FinBERT inference with a bounded per-process result cache."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"
        self._model_name = ""
        self._init_error: str | None = None
        self._init_lock = threading.RLock()
        self._cache_lock = threading.RLock()
        self._cache: OrderedDict[str, FinBertScore] = OrderedDict()

    def warmup(self, settings: Settings) -> bool:
        return self._ensure_loaded(settings)

    def score(self, text: str, settings: Settings) -> FinBertScore | None:
        clipped = (text or "").strip()[: settings.phase1_max_chars]
        if not clipped:
            return FinBertScore(score=0.0, confidence=0.0, label="NEUTRAL")
        cache_key = " ".join(clipped.lower().split())
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached

        if not self._ensure_loaded(settings):
            return None

        try:
            encoded = self._tokenizer(
                clipped,
                return_tensors="pt",
                truncation=True,
                max_length=settings.phase1_finbert_max_length,
                padding=False,
            )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}
            with self._torch.inference_mode():
                output = self._model(**encoded)
                probabilities = self._torch.softmax(output.logits[0], dim=-1).detach().cpu().tolist()
            result = self._from_probabilities(probabilities, self._model.config.id2label)
        except Exception as exc:  # pragma: no cover - runtime/model dependent
            self._init_error = f"inference failed: {exc}"
            logger.warning("FinBERT inference failed; Phase1 will use heuristic fallback: %s", exc)
            return None

        with self._cache_lock:
            self._cache[cache_key] = result
            self._cache.move_to_end(cache_key)
            while len(self._cache) > settings.phase1_cache_size:
                self._cache.popitem(last=False)
        return result

    def status_snapshot(self, configured_provider: str) -> dict[str, Any]:
        with self._cache_lock:
            cache_size = len(self._cache)
        loaded = self._model is not None and self._tokenizer is not None and self._torch is not None
        requested = configured_provider in {"hybrid", "finbert"}
        return {
            "configured_provider": configured_provider,
            "effective_provider": configured_provider if loaded or not requested else "heuristic_fallback",
            "finbert_loaded": loaded,
            "finbert_available": loaded or self._init_error is None,
            "degraded": requested and not loaded,
            "model_name": self._model_name,
            "device": self._device,
            "cache_size": cache_size,
            "init_error": self._init_error,
        }

    def _ensure_loaded(self, settings: Settings) -> bool:
        if self._model is not None and self._tokenizer is not None and self._torch is not None:
            return True
        with self._init_lock:
            if self._model is not None and self._tokenizer is not None and self._torch is not None:
                return True
            try:
                torch_module = importlib.import_module("torch")
                transformers_module = importlib.import_module("transformers")
                tokenizer_cls = transformers_module.AutoTokenizer
                model_cls = transformers_module.AutoModelForSequenceClassification
            except (ImportError, AttributeError) as exc:
                self._init_error = "optional transformers/torch runtime is not installed"
                logger.info("FinBERT runtime unavailable; Phase1 will use heuristic fallback: %s", exc)
                return False

            try:
                model_name = settings.phase1_finbert_model_name
                load_options = {"local_files_only": settings.phase1_finbert_local_files_only}
                tokenizer = tokenizer_cls.from_pretrained(model_name, **load_options)
                model = model_cls.from_pretrained(model_name, use_safetensors=False, **load_options)
                device = self._resolve_device(torch_module, settings.phase1_finbert_device)
                model.to(device)
                model.eval()
                self._validate_labels(model.config.id2label)
                self._torch = torch_module
                self._tokenizer = tokenizer
                self._model = model
                self._device = device
                self._model_name = model_name
                self._init_error = None
                logger.info("Phase1 FinBERT loaded: model=%s device=%s", model_name, device)
                return True
            except Exception as exc:  # pragma: no cover - download/device/model dependent
                self._model = None
                self._tokenizer = None
                self._torch = None
                self._init_error = f"initialization failed: {exc}"
                logger.warning("FinBERT initialization failed; Phase1 will use heuristic fallback: %s", exc)
                return False

    @staticmethod
    def _resolve_device(torch_module: Any, configured: str) -> str:
        requested = str(configured or "auto").lower()
        if requested == "cuda" and torch_module.cuda.is_available():
            return "cuda"
        if requested == "auto" and torch_module.cuda.is_available():
            return "cuda"
        return "cpu"

    @staticmethod
    def _validate_labels(id2label: dict[Any, Any]) -> None:
        labels = {str(value).upper() for value in id2label.values()}
        if "POSITIVE" not in labels or "NEGATIVE" not in labels:
            raise ValueError("FinBERT id2label must contain POSITIVE and NEGATIVE labels")

    @classmethod
    def _from_probabilities(cls, probabilities: list[float], id2label: dict[Any, Any]) -> FinBertScore:
        cls._validate_labels(id2label)
        indexes = {str(label).upper(): int(index) for index, label in id2label.items()}
        positive = float(probabilities[indexes["POSITIVE"]])
        negative = float(probabilities[indexes["NEGATIVE"]])
        neutral = float(probabilities[indexes["NEUTRAL"]]) if "NEUTRAL" in indexes else 0.0
        score = _clamp(positive - negative)
        label = max(
            (("POSITIVE", positive), ("NEGATIVE", negative), ("NEUTRAL", neutral)),
            key=lambda item: item[1],
        )[0]
        return FinBertScore(score=round(score, 4), confidence=round(max(positive, negative, neutral), 4), label=label)


finbert_sentiment_adapter = FinBertSentimentAdapter()


class Phase1Scorer:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        finbert_adapter: FinBertSentimentAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.finbert_adapter = finbert_adapter or finbert_sentiment_adapter

    def score(
        self,
        *,
        current_chunk: str,
        market_data: MarketData,
        section_type: SectionType,
        source_type: SourceType,
    ) -> Phase1ScoreResult:
        settings = self.settings or get_settings()
        heuristic = _score_heuristic(
            current_chunk=current_chunk,
            market_data=market_data,
            section_type=section_type,
            source_type=source_type,
        )
        provider = settings.phase1_provider
        if provider in {"heuristic", "mock"}:
            heuristic.provider = provider
            return heuristic

        finbert = self.finbert_adapter.score(current_chunk, settings)
        if finbert is None:
            heuristic.provider = f"{provider}:heuristic_fallback"
            heuristic.degraded = True
            heuristic.rationale_hint += "; finbert=unavailable"
            return heuristic

        if provider == "finbert":
            return Phase1ScoreResult(
                raw_score=finbert.score,
                confidence=finbert.confidence,
                label=_label_for_score(finbert.score),
                provider="finbert",
                rationale_hint=f"finbert={finbert.score:.4f}; label={finbert.label}",
                heuristic_score=heuristic.raw_score,
                finbert_score=finbert.score,
                finbert_confidence=finbert.confidence,
            )

        heuristic_weight = max(0.0, float(settings.phase1_heuristic_weight))
        finbert_weight = max(0.0, float(settings.phase1_finbert_weight))
        total_weight = heuristic_weight + finbert_weight
        if total_weight <= 0:
            heuristic_weight, finbert_weight, total_weight = 0.55, 0.45, 1.0
        heuristic_weight /= total_weight
        finbert_weight /= total_weight

        combined = heuristic.raw_score * heuristic_weight + finbert.score * finbert_weight
        confidence = heuristic.confidence * heuristic_weight + finbert.confidence * finbert_weight
        conflict = (
            _direction(heuristic.raw_score) != 0
            and _direction(finbert.score) != 0
            and _direction(heuristic.raw_score) != _direction(finbert.score)
        )
        if conflict:
            combined *= 0.80
            confidence -= float(settings.phase1_conflict_penalty)
        else:
            confidence += 0.04 * min(heuristic.confidence, finbert.confidence)
        combined = _clamp(combined)
        confidence = _clamp(confidence, 0.0, 0.98)

        return Phase1ScoreResult(
            raw_score=round(combined, 4),
            confidence=round(confidence, 4),
            label=_label_for_score(combined),
            provider="hybrid",
            rationale_hint=(
                f"hybrid={combined:.4f}; heuristic={heuristic.raw_score:.4f}; "
                f"finbert={finbert.score:.4f}; conflict={str(conflict).lower()}"
            ),
            heuristic_score=heuristic.raw_score,
            finbert_score=finbert.score,
            finbert_confidence=finbert.confidence,
        )

    def warmup(self) -> bool:
        settings = self.settings or get_settings()
        if settings.phase1_provider not in {"hybrid", "finbert"}:
            return True
        return self.finbert_adapter.warmup(settings)

    def status_snapshot(self) -> dict[str, Any]:
        settings = self.settings or get_settings()
        status = self.finbert_adapter.status_snapshot(settings.phase1_provider)
        status.update(
            {
                "heuristic_weight": float(settings.phase1_heuristic_weight),
                "finbert_weight": float(settings.phase1_finbert_weight),
                "conflict_penalty": float(settings.phase1_conflict_penalty),
            }
        )
        return status


phase1_scorer = Phase1Scorer()


def score_phase1(
    *,
    current_chunk: str,
    market_data: MarketData,
    section_type: SectionType,
    source_type: SourceType,
) -> Phase1ScoreResult:
    return phase1_scorer.score(
        current_chunk=current_chunk,
        market_data=market_data,
        section_type=section_type,
        source_type=source_type,
    )


__all__ = [
    "FinBertScore",
    "FinBertSentimentAdapter",
    "Phase1ScoreResult",
    "Phase1Scorer",
    "phase1_scorer",
    "score_phase1",
]
