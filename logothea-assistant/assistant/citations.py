"""생성 후 인용 검증.

답에 쓴 근거 표시가 실제로 넘긴 근거인지, 인용한 문장의 수치가 그 근거 원문에 있는지 코드로 확인한다.
실행 중에는 LLM 채점을 하지 않는다(지연·비용). 검증에 실패해도 답은 지우지 않고 verified:false 로 알린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from assistant.context import Evidence

QUOTE_CHARS = 300

# "[S3]" 와 "[S3, S4]" 두 가지 표기를 모두 받는다.
MARKER_RE = re.compile(r"\[([SNPE]\d+(?:\s*,\s*[SNPE]\d+)*)\]")
_LEADING_MARKERS_RE = re.compile(r"^\s*((?:\[[SNPE]\d+(?:\s*,\s*[SNPE]\d+)*\]\s*)+)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")

_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_SCALES = {
    "trillion": 1e12, "tn": 1e12, "t": 1e12,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "mn": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
    "조": 1e12, "억": 1e8, "만": 1e4,
}
# 단위가 붙은 수치만 본다. 단위 없는 숫자(연도, 분기, 표시 번호)는 오탐이 많다.
_USD_SCALE = r"(?:\s*(?P<scale>trillion|billion|million|thousand|tn|bn|mn|[TBMK])(?![A-Za-z]))?"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("usd", re.compile(r"\$\s*" + _NUM + _USD_SCALE, re.IGNORECASE)),
    ("usd", re.compile(r"(?:USD|US\$)\s*" + _NUM + _USD_SCALE, re.IGNORECASE)),
    ("usd", re.compile(_NUM + r"\s*(?P<scale>trillion|billion|million|thousand)\s+(?:US\s+)?dollars?(?![A-Za-z])",
                       re.IGNORECASE)),
    ("usd", re.compile(_NUM + r"\s*(?P<scale>조|억|만)?\s*달러")),
    # bp 가 pp 보다 먼저여야 "basis points" 가 bp 로 잡힌다.
    ("bp", re.compile(_NUM + r"\s*(?:bps?|basis\s+points?|베이시스\s*포인트)(?![A-Za-z])", re.IGNORECASE)),
    # 퍼센트포인트는 퍼센트와 같은 단위로 비교한다. pct 보다 먼저여야 "%p" 가 통째로 잡힌다.
    ("pct", re.compile(_NUM + r"\s*(?:%\s*p(?![A-Za-z])|%\s*포인트|퍼센트\s*포인트|포인트"
                       r"|percentage\s+points?|points?(?![A-Za-z]))", re.IGNORECASE)),
    ("pct", re.compile(_NUM + r"\s*(?:%|퍼센트|percent(?![A-Za-z]))", re.IGNORECASE)),
    ("mult", re.compile(_NUM + r"\s*(?:x(?![A-Za-z])|times(?![A-Za-z])|배(?!당))", re.IGNORECASE)),
)


@dataclass(frozen=True)
class Quantity:
    kind: str
    value: float
    tolerance: float


@dataclass
class VerificationResult:
    citations: list[dict[str, Any]]
    warnings: list[str]


def extract_quantities(text: str) -> list[Quantity]:
    claimed: list[tuple[int, int]] = []
    found: list[Quantity] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end in claimed):
                continue
            claimed.append((start, end))
            found.append(_quantity(kind, match))
    return found


def _quantity(kind: str, match: re.Match[str]) -> Quantity:
    raw = match.group("num").replace(",", "")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    scale_name = match.groupdict().get("scale")
    scale = _SCALES[scale_name.lower()] if scale_name else 1.0
    value = float(raw) * scale
    # 답이 쓴 자릿수만큼의 반올림은 같은 수치로 본다(2.63% → 2.6%).
    tolerance = 0.5 * (10 ** -decimals) * scale
    if kind == "bp":
        return Quantity("pct", value / 100, tolerance / 100)
    return Quantity(kind, value, tolerance)


def _matches(claim: Quantity, source: Quantity) -> bool:
    return claim.kind == source.kind and abs(claim.value - source.value) <= max(claim.tolerance, source.tolerance) + 1e-9


def find_markers(text: str) -> list[str]:
    """문장에서 근거 표시를 나타난 순서대로 꺼낸다. "[S3, S4]" 는 S3, S4 로 풀어 준다."""
    return [marker.strip() for group in MARKER_RE.findall(text) for marker in group.split(",")]


def split_sentences(answer: str) -> list[str]:
    sentences: list[str] = []
    for piece in _SENTENCE_SPLIT_RE.split(answer):
        if not piece or not piece.strip():
            continue
        # "…늘었습니다. [S3] 다음 문장" 처럼 표시가 마침표 뒤에 오면 앞 문장의 인용으로 본다.
        leading = _LEADING_MARKERS_RE.match(piece)
        if leading and sentences:
            sentences[-1] = f"{sentences[-1]} {leading.group(1).strip()}"
            piece = piece[leading.end():]
        if piece.strip():
            sentences.append(piece.strip())
    return sentences


def verify_citations(answer: str, evidence: dict[str, Evidence]) -> VerificationResult:
    order: list[str] = []
    failed: set[str] = set()
    warnings: list[str] = []

    for sentence in split_sentences(answer):
        markers = find_markers(sentence)
        for marker in markers:
            if marker not in order:
                order.append(marker)
            if marker not in evidence:
                failed.add(marker)
                _warn(warnings, f"unknown_marker:{marker}")
        claims = extract_quantities(MARKER_RE.sub(" ", sentence))
        if not claims:
            continue
        if not markers:
            _warn(warnings, "uncited_number")
            continue
        known = [marker for marker in markers if marker in evidence]
        sources = [quantity for marker in known for quantity in extract_quantities(evidence[marker].text)]
        if any(not any(_matches(claim, source) for source in sources) for claim in claims):
            failed.update(known)
            _warn(warnings, "number_mismatch")

    citations = [_citation(marker, evidence.get(marker), marker not in failed) for marker in order]
    return VerificationResult(citations=citations, warnings=warnings)


def _warn(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _citation(marker: str, item: Evidence | None, verified: bool) -> dict[str, Any]:
    if item is None:
        return {"marker": marker, "type": None, "ref": None, "title": None, "source": None, "published_at": None,
                "start_ms": None, "speaker": None, "quote": None, "verified": False}
    return {"marker": marker, "type": item.type, "ref": item.ref, "title": item.title, "source": item.source,
            "published_at": item.published_at, "start_ms": item.start_ms, "speaker": item.speaker,
            "quote": item.text[:QUOTE_CHARS], "verified": verified}
