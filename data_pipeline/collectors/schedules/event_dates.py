"""Local date semantics shared by schedule extraction and live identity checks.

These helpers exclude *explicitly labelled* non-event dates; they neither
invent a missing call date nor choose between competing event dates. Keep the
original evidence for fiscal-period matching and for diagnostics.
"""
from __future__ import annotations

import re


_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
# Also recognize partial-year visible dates: callers may supply their event's
# known year separately. Longer alternatives precede any contained match.
_DATE = re.compile(
    rf"\b{_MONTH}\.?\s+\d{{1,2}}(?!\d)(?:st|nd|rd|th)?(?:,?\s+20\d{{2}})?\b|"
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?(?:,?\s+20\d{{2}})?\b|"
    r"(?<!\d)20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?!\d)|"
    r"(?<!\d)\d{1,2}[-/]\d{1,2}[-/](?:20\d{2}|\d{2})(?!\d)|"
    r"(?<!\d)20\d{6}(?!\d)",
    re.IGNORECASE,
)
_WEEKDAY = r"(?:(?:Mon|Tues?|Wed(?:nes)?|Thurs?|Fri|Satur?|Sun)(?:day)?\.?\s*,?\s*)?"
_SEPARATOR = r"[\s:='\"\-–—]*"
# A short date list can belong to one period-ended label. Replacing preceding
# dates with a token allows this without swallowing a subsequent call sentence.
_DATE_LIST = r"(?:__DATE__\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)){0,3}"
_TRAILER = rf"\s*(?:on\s+)?{_SEPARATOR}{_WEEKDAY}{_DATE_LIST}$"
_PERIOD_END = re.compile(
    r"\b(?:(?:fiscal\s+|financial\s+)?(?:quarters?|years?|periods?|months?|weeks?)"
    r"[\s-]+(?:ended|ending|ends?)|(?:fiscal\s+)?(?:quarter|year|period)[\s-]+end"
    r"(?:\s+date)?|(?:end\s+of\s+(?:the\s+)?(?:fiscal\s+)?(?:quarter|year|period)))"
    + _TRAILER,
    re.IGNORECASE,
)
_AS_OF = re.compile(
    r"\b(?:balance\s+sheets?|financial\s+(?:position|statements?)|"
    r"(?:quarter|year|period)[\s-]+end)\s*(?:as\s+of|at)" + _TRAILER,
    re.IGNORECASE,
)
_PUBLICATION = re.compile(
    r"\b(?:posted|published|updated|(?:last\s+)?modified|"
    r"publication\s+date|(?:press\s+|news\s+)?release\s+date|"
    r"datePublished|dateModified)" + _TRAILER,
    re.IGNORECASE,
)
_AVAILABILITY = re.compile(
    r"\b(?:available\s+(?:until|through)|expires?|expiration(?:\s+date)?|"
    r"registration\s+(?:opens|closes|deadline)|registration\s+deadline\s+(?:is|of))"
    + _TRAILER,
    re.IGNORECASE,
)


def non_event_date_reason(text: str, start: int, end: int) -> str | None:
    """Explain whether the date at ``[start:end]`` has a non-event label.

    Matching is deliberately local and anchored immediately before the date.
    A quarter-end elsewhere on an event card must not hide its real call date.
    Unlabelled dates, actual call-end dates and rescheduling dates stay intact.
    """
    if not 0 <= start < end <= len(text):
        return None
    prefix = _DATE.sub("__DATE__", text[max(0, start - 320):start])
    for pattern, reason in (
        (_PERIOD_END, "financial_period_end"),
        (_AS_OF, "financial_as_of"),
        (_PUBLICATION, "document_publication"),
        (_AVAILABILITY, "availability_or_registration"),
    ):
        if pattern.search(prefix):
            return reason
    return None


def mask_non_event_dates(text: str) -> str:
    """Blank labelled dates only, retaining string length and all other text."""
    ignored = [match.span() for match in _DATE.finditer(text)
               if non_event_date_reason(text, *match.span())]
    for start, end in reversed(ignored):
        text = text[:start] + " " * (end - start) + text[end:]
    return text
