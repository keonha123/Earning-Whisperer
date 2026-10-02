from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx


WEBCAST_TERMS = (
    ("webcast", 70),
    ("listen live", 60),
    ("earnings call", 55),
    ("earnings", 35),
    ("conference call", 35),
    ("audio", 30),
    ("listen", 25),
    ("live", 20),
    ("replay", 10),
    ("presentation", 8),
    ("event", 6),
)
STRONG_WEBCAST_TERMS = ("webcast", "listen", "audio", "conference call", "live")
EVENT_DETAIL_PATH_PATTERN = re.compile(r"/events?(?:[-/]|$)|/event-details?(?:[-/]|$)", re.IGNORECASE)
EVENT_DETAIL_CONTEXT_TERMS = ("earnings", "results", "quarter", "financial")
NON_PLAYBACK_TERMS = (
    "skip to main",
    "skip to content",
    "calendar",
    "configuration",
    "system test",
    "help",
    "download",
    "copyright",
    "slide",
    "investor presentation",
    "prepared remarks",
    "transcript",
    "press release",
    "event announcement",
    "open event link",
    "pdf file",
    "financial tables",
)
NON_PLAYBACK_PATH_SUFFIXES = (".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx")
EARNINGS_CONTEXT_TERMS = (
    "earnings",
    "financial results",
    "quarterly results",
    "quarterly corporate performance",
    "quarter",
)
GENERALIZED_ACTION_TERMS = frozenset(
    {"play", "listen", "watch", "start", "unmute", "replay", "webcast", "audio", "join"}
)
GENERALIZED_PATH_TERMS = (
    "/webcast",
    "/webcasts",
    "/replay",
    "/events",
    "/media",
    "/mmc/",
)
GENERALIZED_NON_PLAYBACK_TERMS = (
    "join our team",
    "join us",
    "careers",
    "shop watch",
    "overview",
)
QUARTER_ALIASES = {
    "q1": ("q1", "1q", "first quarter", "1st quarter"),
    "q2": ("q2", "2q", "second quarter", "2nd quarter"),
    "q3": ("q3", "3q", "third quarter", "3rd quarter"),
    "q4": ("q4", "4q", "fourth quarter", "4th quarter"),
}
EVENT_DATE_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(20\d{2})\b",
    re.IGNORECASE,
)
NUMERIC_EVENT_DATE_PATTERN = re.compile(
    r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d{2})\b"
)
MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class WebcastCandidate:
    candidate_id: str
    selectors: tuple[str, ...]
    frame_hostname: str | None
    text: str
    aria_label: str
    title: str
    href_path: str | None
    tag_name: str
    rect: dict[str, float]
    in_navigation: bool = False
    context_text: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WebcastCandidate":
        return cls(
            candidate_id=str(value["candidate_id"]),
            selectors=tuple(str(selector) for selector in value.get("selectors", []) if selector),
            frame_hostname=value.get("frame_hostname") or None,
            text=str(value.get("text") or ""),
            aria_label=str(value.get("aria_label") or ""),
            title=str(value.get("title") or ""),
            href_path=value.get("href_path") or None,
            tag_name=str(value.get("tag_name") or ""),
            rect={key: float(number) for key, number in (value.get("rect") or {}).items()},
            in_navigation=bool(value.get("in_navigation")),
            context_text=str(value.get("context_text") or ""),
        )

    def prompt_value(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "text": self.text,
            "aria_label": self.aria_label,
            "title": self.title,
            "href_path": self.href_path,
            "tag_name": self.tag_name,
            "rect": self.rect,
            "in_navigation": self.in_navigation,
            "context_text": self.context_text,
        }


@dataclass
class WebcastRecipe:
    domain: str
    selectors: tuple[str, ...]
    frame_hostname: str | None
    target_text: str
    target_href_path: str | None
    strategy: str
    lifecycle: str
    confidence: float
    evidence: dict[str, Any]
    recipe_id: int | None = None

    @property
    def recipe_key(self) -> str:
        return recipe_key(self.domain, self.selectors, self.frame_hostname, self.lifecycle)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "WebcastRecipe":
        selectors = _json_list(record.get("selector_json"))
        evidence = _json_object(record.get("evidence_json"))
        return cls(
            recipe_id=int(record["id"]),
            domain=str(record["domain"]),
            selectors=tuple(selectors),
            frame_hostname=record.get("frame_hostname") or None,
            target_text=str(record.get("target_text") or ""),
            target_href_path=record.get("target_href_path") or None,
            strategy=str(record.get("strategy") or "recipe"),
            lifecycle=str(record.get("lifecycle") or "unknown"),
            confidence=float(record.get("confidence") or 0),
            evidence=evidence,
        )

    def database_value(self) -> dict[str, Any]:
        return {
            "recipe_key": self.recipe_key,
            "domain": self.domain,
            "selector_json": json.dumps(list(self.selectors), ensure_ascii=True),
            "frame_hostname": self.frame_hostname,
            "target_text": self.target_text[:500],
            "target_href_path": self.target_href_path,
            "strategy": self.strategy,
            "lifecycle": self.lifecycle,
            "confidence": self.confidence,
            "evidence_json": json.dumps(self.evidence, ensure_ascii=True),
        }


@dataclass(frozen=True)
class VisionSelection:
    candidate_id: str
    confidence: float
    reason: str
    x: float = 0
    y: float = 0


@dataclass(frozen=True)
class LearningSnapshot:
    screenshot_path: Path
    candidates_path: Path
    candidates: tuple[WebcastCandidate, ...]


@dataclass(frozen=True)
class GeneralizedWebcastPattern:
    """Cross-domain evidence extracted from an audio-verified recipe."""

    action_tokens: frozenset[str]
    href_tokens: frozenset[str]
    success_count: int = 1


def _generalized_tokens(value: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    return frozenset(word for word in words if len(word) > 2)


def make_generalized_patterns(records: Iterable[dict[str, Any]]) -> tuple[GeneralizedWebcastPattern, ...]:
    patterns: list[GeneralizedWebcastPattern] = []
    for record in records:
        target_text = str(record.get("target_text") or "")
        target_href = str(record.get("target_href_path") or "")
        action_tokens = _generalized_tokens(target_text) & GENERALIZED_ACTION_TERMS
        if not action_tokens:
            continue
        patterns.append(
            GeneralizedWebcastPattern(
                action_tokens=action_tokens,
                href_tokens=_generalized_tokens(target_href),
                success_count=max(1, int(record.get("success_count") or 1)),
            )
        )
    return tuple(patterns)


def generalized_candidate_bonus(
    candidate: WebcastCandidate,
    patterns: Iterable[GeneralizedWebcastPattern],
) -> int:
    """Score reusable action evidence without copying another site's selectors."""
    candidate_label = " ".join(
        value for value in (candidate.text, candidate.aria_label, candidate.title) if value
    )
    candidate_actions = _generalized_tokens(candidate_label) & GENERALIZED_ACTION_TERMS
    if not candidate_actions:
        return 0

    candidate_href = (candidate.href_path or "").lower()
    best_bonus = 0
    for pattern in patterns:
        overlap = len(candidate_actions & pattern.action_tokens)
        if overlap == 0 and not candidate_actions.intersection(GENERALIZED_ACTION_TERMS):
            continue
        bonus = (12 if overlap else 8) + min(12, pattern.success_count * 2)
        if candidate_actions == pattern.action_tokens:
            bonus += 10
        if any(term in candidate_href for term in GENERALIZED_PATH_TERMS):
            bonus += 4
        best_bonus = max(best_bonus, bonus)
    return best_bonus


def _candidate_period_mismatch(
    candidate: WebcastCandidate,
    *,
    target_year: int | None,
    target_quarter: str | None,
) -> bool:
    """Reject an explicitly different quarter while keeping generic replay links."""
    if target_year is None and not target_quarter:
        return False
    label = " ".join(
        value
        for value in (
            candidate.text,
            candidate.aria_label,
            candidate.title,
            candidate.href_path or "",
            candidate.context_text,
        )
        if value
    ).lower()
    years = set(re.findall(r"\b20\d{2}\b", label))
    if target_year is not None and years and str(target_year) not in years:
        return True
    normalized_quarter = (target_quarter or "").lower().replace(" ", "")
    target_key = next(
        (key for key, aliases in QUARTER_ALIASES.items() if normalized_quarter in aliases),
        normalized_quarter if normalized_quarter in QUARTER_ALIASES else "",
    )
    if not target_key:
        return False
    explicit_quarters = {
        key
        for key, aliases in QUARTER_ALIASES.items()
        if any(alias in label for alias in aliases)
    }
    return bool(explicit_quarters and target_key not in explicit_quarters)


def candidate_event_date(candidate: WebcastCandidate) -> date | None:
    """Extract a calendar date from an event link or its nearest event block."""
    label = " ".join(
        value
        for value in (
            candidate.text,
            candidate.aria_label,
            candidate.title,
            candidate.context_text,
        )
        if value
    )
    match = EVENT_DATE_PATTERN.search(label)
    if match:
        month = MONTH_NUMBERS[match.group(1)[:3].lower()]
        try:
            return date(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            return None

    numeric_match = NUMERIC_EVENT_DATE_PATTERN.search(label)
    if numeric_match:
        try:
            return date(
                int(numeric_match.group(3)),
                int(numeric_match.group(1)),
                int(numeric_match.group(2)),
            )
        except ValueError:
            return None
    return None


def domain_for_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def recipe_key(
    domain: str,
    selectors: tuple[str, ...],
    frame_hostname: str | None,
    lifecycle: str = "unknown",
) -> str:
    source = "\n".join([domain.lower(), lifecycle.lower(), frame_hostname or "", *selectors])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def choose_heuristic_candidate(
    candidates: list[WebcastCandidate],
    generalized_patterns: Iterable[GeneralizedWebcastPattern] = (),
    *,
    lifecycle: str = "unknown",
    target_year: int | None = None,
    target_quarter: str | None = None,
    reference_date: date | None = None,
) -> WebcastCandidate | None:
    generalized_patterns = tuple(generalized_patterns)
    reference_date = reference_date or datetime.now(timezone.utc).date()
    scored: list[tuple[int, int, int, WebcastCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not candidate.selectors:
            continue
        action_haystack = " ".join(
            value
            for value in (
                candidate.text,
                candidate.aria_label,
                candidate.title,
                candidate.href_path or "",
            )
            if value
        ).lower()
        haystack = " ".join(
            value for value in (action_haystack, candidate.context_text) if value
        )
        visible_label = " ".join(
            value for value in (candidate.text, candidate.aria_label, candidate.title) if value
        ).lower()
        if _candidate_period_mismatch(
            candidate,
            target_year=target_year,
            target_quarter=target_quarter,
        ):
            continue
        event_date = candidate_event_date(candidate)
        if lifecycle == "replay" and event_date and event_date > reference_date:
            continue
        href_path = (candidate.href_path or "").lower()
        event_detail_link = bool(EVENT_DETAIL_PATH_PATTERN.search(href_path)) and any(
            term in haystack for term in EVENT_DETAIL_CONTEXT_TERMS
        )
        if not any(term in action_haystack for term in STRONG_WEBCAST_TERMS) and not event_detail_link:
            continue
        if any(term in visible_label for term in NON_PLAYBACK_TERMS):
            continue
        if lifecycle == "replay" and any(
            term in visible_label for term in ("register", "registration")
        ):
            continue
        if href_path.split("?", maxsplit=1)[0].endswith(NON_PLAYBACK_PATH_SUFFIXES):
            continue
        score = sum(points for term, points in WEBCAST_TERMS if term in haystack)
        if event_detail_link:
            score += 18
        score += _nearby_earnings_context_score(candidates, index)
        if candidate.in_navigation:
            if lifecycle == "replay" and any(
                term in visible_label
                for term in (
                    "webcast replay",
                    "listen to webcast",
                    "watch replay",
                    "click here for webcast",
                )
            ):
                score -= 10
            elif lifecycle == "replay" and "/attendee/" in href_path:
                score -= 10
            else:
                score -= 80
        if candidate.tag_name == "a" and candidate.href_path:
            score += 5
        if score > 0:
            scored.append(
                (
                    score,
                    event_date.toordinal() if event_date else 0,
                    -index,
                    candidate,
                )
            )

    if not scored:
        fallback_scored: list[tuple[int, int, int, WebcastCandidate]] = []
        for index, candidate in enumerate(candidates):
            label = " ".join(
                value for value in (candidate.text, candidate.aria_label, candidate.title) if value
            ).lower()
            if candidate.in_navigation or any(
                term in label
                for term in (*NON_PLAYBACK_TERMS, *GENERALIZED_NON_PLAYBACK_TERMS)
            ):
                continue
            if _candidate_period_mismatch(
                candidate,
                target_year=target_year,
                target_quarter=target_quarter,
            ):
                continue
            event_date = candidate_event_date(candidate)
            if lifecycle == "replay" and event_date and event_date > reference_date:
                continue
            bonus = generalized_candidate_bonus(candidate, generalized_patterns)
            if bonus > 0:
                fallback_scored.append(
                    (
                        bonus,
                        event_date.toordinal() if event_date else 0,
                        -index,
                        candidate,
                    )
                )
        if not fallback_scored:
            if lifecycle == "replay" and (target_year is not None or target_quarter):
                return choose_heuristic_candidate(
                    candidates,
                    generalized_patterns,
                    lifecycle=lifecycle,
                    reference_date=reference_date,
                )
            return None
        fallback_scored.sort(key=lambda item: item[:3], reverse=True)
        return fallback_scored[0][3]
    scored.sort(key=lambda item: item[:3], reverse=True)
    return scored[0][3]


def _nearby_earnings_context_score(candidates: list[WebcastCandidate], index: int) -> int:
    """Associate a generic 'Listen to Webcast' link with the event title just above it."""
    candidate = candidates[index]
    candidate_context = candidate.context_text.lower()
    if candidate_context and not any(
        term in candidate_context for term in EARNINGS_CONTEXT_TERMS
    ):
        return 0
    if candidate_context and any(
        term in candidate_context for term in EARNINGS_CONTEXT_TERMS
    ):
        return 150
    candidate_frame = candidate.candidate_id.split("-element-", maxsplit=1)[0]
    candidate_top = candidate.rect.get("y", 0.0)
    for previous in reversed(candidates[:index]):
        previous_frame = previous.candidate_id.split("-element-", maxsplit=1)[0]
        if previous_frame != candidate_frame:
            continue
        label = " ".join(
            value for value in (previous.text, previous.aria_label, previous.title) if value
        ).lower()
        if not label or "listen to webcast" in label:
            continue
        previous_bottom = previous.rect.get("y", 0.0) + previous.rect.get("height", 0.0)
        distance = candidate_top - previous_bottom
        if distance < -4:
            continue
        if distance > 180:
            break
        if any(term in label for term in EARNINGS_CONTEXT_TERMS):
            return 150
        return 0
    return 0


def make_recipe(
    page_url: str,
    candidate: WebcastCandidate,
    *,
    strategy: str,
    lifecycle: str = "unknown",
    confidence: float,
    snapshot: LearningSnapshot | None = None,
    vision_reason: str | None = None,
) -> WebcastRecipe:
    evidence: dict[str, Any] = {
        "candidate": candidate.prompt_value(),
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    if snapshot:
        evidence["screenshot_path"] = str(snapshot.screenshot_path)
        evidence["candidates_path"] = str(snapshot.candidates_path)
    if vision_reason:
        evidence["vision_reason"] = vision_reason[:500]

    return WebcastRecipe(
        domain=domain_for_url(page_url),
        selectors=candidate.selectors,
        frame_hostname=candidate.frame_hostname,
        target_text=(candidate.text or candidate.aria_label or candidate.title)[:500],
        target_href_path=candidate.href_path,
        strategy=strategy,
        lifecycle=lifecycle.lower(),
        confidence=max(0.0, min(1.0, confidence)),
        evidence=evidence,
    )


def artifact_paths(ticker: str, page_url: str) -> tuple[Path, Path]:
    root = Path(
        os.getenv(
            "WEBCAST_ARTIFACTS_DIR",
            str(Path(__file__).resolve().parents[2] / ".artifacts" / "webcast"),
        )
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_hash = hashlib.sha256(page_url.encode("utf-8")).hexdigest()[:10]
    prefix = f"{ticker.upper()}-{stamp}-{source_hash}"
    return root / f"{prefix}.jpg", root / f"{prefix}.json"


class OpenAIVisionSelector:
    """Optional screenshot selector. DOM heuristics remain available without an API key."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.enabled = os.getenv("WEBCAST_VISION_ENABLED", "false").lower() == "true"
        self.model = os.getenv("WEBCAST_VISION_MODEL", "gpt-5.6-luna").strip()

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def select(
        self,
        screenshot_path: Path,
        candidates: list[WebcastCandidate],
        *,
        ticker: str,
    ) -> VisionSelection | None:
        if not self.available:
            return None

        try:
            image_data = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
            mime_type = "image/jpeg" if screenshot_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            candidate_payload = [candidate.prompt_value() for candidate in candidates[:80]]
            prompt = (
                "Find the control that opens the current earnings webcast or live earnings call. "
                "Choose only one supplied candidate_id when a suitable DOM candidate is available. "
                "Do not choose navigation menu entries, historical annual-report links, or generic investor pages. "
                "If no supplied candidate corresponds to the visual target, provide screenshot coordinates "
                "for the center of a clickable control in x/y; otherwise x and y must be 0. "
                f"Ticker: {ticker}. Candidates: {json.dumps(candidate_payload, ensure_ascii=True)}"
            )
            payload = {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime_type};base64,{image_data}",
                                "detail": "low",
                            },
                        ],
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "webcast_target",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "confidence": {"type": "number"},
                                "reason": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                            },
                            "required": ["candidate_id", "confidence", "reason", "x", "y"],
                            "additionalProperties": False,
                        },
                    }
                },
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            return parse_vision_selection(extract_response_text(response.json()))
        except Exception as exc:
            print(f"[WebcastLearning] vision selection skipped: {str(exc)[:180]}")
            return None


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    texts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts)


def parse_vision_selection(value: str) -> VisionSelection | None:
    try:
        parsed = json.loads(value)
        confidence = float(parsed.get("confidence", 0))
        return VisionSelection(
            candidate_id=str(parsed.get("candidate_id") or ""),
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(parsed.get("reason") or "")[:500],
            x=float(parsed.get("x", 0) or 0),
            y=float(parsed.get("y", 0) or 0),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def write_snapshot_metadata(
    candidates_path: Path,
    *,
    page_url: str,
    candidates: list[WebcastCandidate],
) -> None:
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps(
            {
                "page_url": _safe_url(page_url),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "candidates": [candidate.prompt_value() for candidate in candidates],
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
