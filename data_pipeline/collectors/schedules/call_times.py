"""Conservative, scoped earnings-call start evidence parsing (no network or DB)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import html as html_lib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lxml import html

from .event_routes import fiscal_period
from .event_dates import non_event_date_reason

MONTHS = {name: n for n, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
DATE_RE = re.compile(
    r'\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+'
    r'(?P<day>\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(?P<year>20\d{2}))?', re.I)
DMY_DATE_RE = re.compile(
    r'(?<!\d)(?P<day>\d{1,2})(?!\d)(?:st|nd|rd|th)?\s+'
    r'(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?'
    r'(?:,?\s+(?P<year>20\d{2}))?', re.I)
ISO_DATE_RE = re.compile(r'(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)')
ISO_TIME_RE = re.compile(r'(?<!\d)20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})(?!\d)', re.I)
CALL_RE = re.compile(
    r'\b(?:earnings\s+(?:release\s+)?conference\s+call|earnings\s+call|conference\s+call|results\s+call|teleconference|webcast|'
    r'(?:live\s+)?(?:Q\s*&\s*A|question(?:s)?[-\s]+and[-\s]+answer(?:s)?)\s+(?:session|call))\b', re.I)
NEGATIVE_RE = re.compile(
    r'\b(?:releas(?:e|ed|ing)|publish(?:ed|ing)?|posted|prepared\s+remarks|'
    r'(?:audio\s+)?replay|(?:pre[-\s]?recorded)|endDate|datePublished|dateModified|'
    r'expir(?:es|y|ation)|available\s+(?:until|through)|registration\s+(?:opens|closes)|'
    r'(?:investor|industry|technology|healthcare|banking)\s+conference|annual\s+meeting)\b', re.I)
ZONE_RE = (
    r'Eastern(?:\s+(?:Daylight|Standard))?\s+Time|Central(?:\s+(?:Daylight|Standard))?\s+Time|'
    r'Mountain(?:\s+(?:Daylight|Standard))?\s+Time|Pacific(?:\s+(?:Daylight|Standard))?\s+Time|'
    r'EDT|EST|CDT|CST|MDT|MST|PDT|PST|UTC|GMT|ET|CT|MT|PT')
CLOCK_RE = re.compile(
    rf'(?<![\d:])(?P<hour>\d{{1,2}})(?::(?P<minute>\d{{2}}))?\s*'
    rf'(?P<meridiem>a\.?\s*m\.?|p\.?\s*m\.?)\s*(?:\(\s*)?'
    rf'(?P<timezone>{ZONE_RE})(?:\s*\))?\b', re.I)
REGIONAL_ZONES = {'ET': 'America/New_York', 'CT': 'America/Chicago',
                  'MT': 'America/Denver', 'PT': 'America/Los_Angeles',
                  'EASTERN TIME': 'America/New_York', 'CENTRAL TIME': 'America/Chicago',
                  'MOUNTAIN TIME': 'America/Denver', 'PACIFIC TIME': 'America/Los_Angeles'}
FIXED_ZONES = {'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5, 'MST': -7, 'MDT': -6,
               'PST': -8, 'PDT': -7, 'UTC': 0, 'GMT': 0}
for region, standard, daylight in [('EASTERN', -5, -4), ('CENTRAL', -6, -5),
                                    ('MOUNTAIN', -7, -6), ('PACIFIC', -8, -7)]:
    FIXED_ZONES[region + ' STANDARD TIME'] = standard
    FIXED_ZONES[region + ' DAYLIGHT TIME'] = daylight
UNAVAILABLE_RE = re.compile(r'\b(cancelled|canceled|postponed|(?:time|date)\s+(?:to\s+be\s+(?:announced|determined)|TBD)|TBD)\b', re.I)
MAX_DOCUMENT_CHARS = 1_000_000
BLOCK_PREFIX = 'CALL_TIME_BLOCK:'
# A generic "webcast" link does not turn an Investor Day or an analyst-only
# follow-up into the earnings call. Keep this rule independent of any issuer.
NON_EARNINGS_EVENT_RE = re.compile(
    r'\b(?:(?:investor|analyst|capital\s+markets?|technology)\s+day|'
    r'annual\s+(?:general\s+|shareholders?\s+)?meeting|'
    r'(?:investor|industry|technology|healthcare|banking)\s+conference|'
    r'post[-\s]+earnings\s+analyst\s+call)\b', re.I)
EXPLICIT_EARNINGS_CALL_RE = re.compile(
    r'\b(?:earnings\s+(?:release\s+)?(?:conference\s+)?call|'
    r'(?:financial\s+)?results\s+(?:conference\s+)?call)\b', re.I)
HEADING_XPATH = './/h1|.//h2|.//h3|.//h4|.//*[@role="heading"]'


def _non_earnings_event(value: str) -> bool:
    # Explicit earnings-call prose may mention a later investor event; the
    # clause-level association rules still decide which clock belongs to it.
    return bool(NON_EARNINGS_EVENT_RE.search(value) and not EXPLICIT_EARNINGS_CALL_RE.search(value))


def _matches_period(value: str, fiscal_year: int | None, fiscal_quarter: str | None) -> bool:
    year, quarter = fiscal_period(value)
    return not ((fiscal_year and year and str(fiscal_year) != str(year))
                or (fiscal_quarter and quarter and str(fiscal_quarter).upper() != quarter))


def _allowed_event_scope(value: str, fiscal_year: int | None, fiscal_quarter: str | None) -> bool:
    return not _non_earnings_event(value) and _matches_period(value, fiscal_year, fiscal_quarter)


def _event_dates(value: str, expected_date: date) -> set[date]:
    dates = set()
    for match in (*DATE_RE.finditer(value), *DMY_DATE_RE.finditer(value)):
        if non_event_date_reason(value, *match.span()):
            continue
        try:
            dates.add(date(int(match.group('year') or expected_date.year),
                           MONTHS[match.group('month')[:3].lower()], int(match.group('day'))))
        except ValueError:
            pass
    for match in ISO_DATE_RE.finditer(value):
        if non_event_date_reason(value, *match.span()):
            continue
        try:
            dates.add(date(*map(int, match.groups())))
        except ValueError:
            pass
    return dates



@dataclass(frozen=True)
class CallTimeCandidate:
    webcast_date: date
    scheduled_at_utc: datetime
    source_timezone: str
    evidence: str


@dataclass(frozen=True)
class CallTimeResult:
    candidates: tuple[CallTimeCandidate, ...] = ()
    conflicted: bool = False
    unavailable_reason: str | None = None

    @property
    def selected(self) -> CallTimeCandidate | None:
        return self.candidates[0] if len(self.candidates) == 1 and not self.conflicted and not self.unavailable_reason else None

    @property
    def status(self) -> str:
        return 'ambiguous' if self.conflicted else self.unavailable_reason or ('verified' if self.selected else 'unknown')



def seasonal_abbreviation_conflict(candidate: CallTimeCandidate, verified_utc: datetime | None) -> bool:
    """Detect a standard-zone label that could misstate a verified DST clock.

    This never changes parsing of literal CST/EST/etc. A previously verified
    instant is required, and only the *same local date and wall clock* in the
    corresponding US region qualifies. Such a conflicting label cannot alone
    move a known call one hour later; it needs independent revalidation.
    """
    regions = {
        'EST': 'America/New_York', 'EASTERN STANDARD TIME': 'America/New_York',
        'CST': 'America/Chicago', 'CENTRAL STANDARD TIME': 'America/Chicago',
        'MST': 'America/Denver', 'MOUNTAIN STANDARD TIME': 'America/Denver',
        'PST': 'America/Los_Angeles', 'PACIFIC STANDARD TIME': 'America/Los_Angeles',
    }
    region = regions.get(candidate.source_timezone.upper())
    if region is None or verified_utc is None:
        return False
    if verified_utc.tzinfo is None:
        verified_utc = verified_utc.replace(tzinfo=timezone.utc)
    verified_utc = verified_utc.astimezone(timezone.utc)
    regional = verified_utc.astimezone(ZoneInfo(region))
    standard = timezone(timedelta(hours=FIXED_ZONES[candidate.source_timezone.upper()]))
    printed = candidate.scheduled_at_utc.astimezone(standard)
    return bool(
        regional.dst() == timedelta(hours=1)
        and candidate.scheduled_at_utc - verified_utc == timedelta(hours=1)
        and printed.replace(tzinfo=None) == regional.replace(tzinfo=None)
    )

def _compact(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def _visible(node) -> bool:
    if node is None or not isinstance(node.tag, str):
        return False
    for ancestor in (node, *node.iterancestors()):
        if (ancestor.tag in {'script', 'style', 'nav', 'footer', 'aside', 'template'}
                or ancestor.get('hidden') is not None
                or str(ancestor.get('aria-hidden', '')).lower() == 'true'
                or re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', str(ancestor.get('style') or ''), re.I)):
            return False
    return True


def _text_owner(text_node):
    # lxml assigns a tail string to the preceding node, including comments and
    # scripts. Its visibility and event scope actually belong to the parent.
    owner = text_node.getparent()
    return owner.getparent() if owner is not None and text_node.is_tail else owner


def _text(node) -> str:
    return _compact(' '.join(str(value) for value in node.xpath('.//text()')
                             if _visible(_text_owner(value))))


def schedule_time_text(document) -> str:
    """Serialize separate event scopes; never flatten neighbouring event cards.

    Labels, clocks and <time> attributes can live on separate lines of one card.
    Each serialized block remains inspectable text, including non-ASCII names.
    """
    blocks: list[dict[str, Any]] = []
    chosen: set[Any] = set()
    for text_node in document.xpath('//text()'):
        if not CALL_RE.search(str(text_node)) or not _visible(_text_owner(text_node)):
            continue
        node = _text_owner(text_node)
        selected = None
        for ancestor in (node, *node.iterancestors()):
            if ancestor.tag in {'html', 'body'} and len(ancestor.xpath('.//article|.//section|.//li|.//tr')):
                break
            local_text = _text(ancestor)
            if len(local_text) > 6000:
                break
            # Do not jump out of an explicit card to borrow another card's time.
            has_clock = bool(CLOCK_RE.search(local_text) or ISO_TIME_RE.search(local_text)
                             or ancestor.xpath('.//time[@datetime]|.//*[@itemprop="startDate"]'))
            has_date = bool(DATE_RE.search(local_text) or DMY_DATE_RE.search(local_text) or ISO_DATE_RE.search(local_text)
                            or ancestor.xpath('.//time[@datetime]|.//*[@itemprop="startDate"]'))
            if has_clock and has_date:
                selected = ancestor
                break
            if ancestor.tag in {'article', 'li', 'tr'} or ancestor.get('itemscope') is not None:
                selected = ancestor
                break
            # A section/div with a heading is a card boundary when siblings have headings.
            parent = ancestor.getparent()
            if (ancestor.tag in {'section', 'div'} and ancestor.xpath('./h1|./h2|./h3|./h4')
                    and parent is not None and len(parent.xpath('./*/h1|./*/h2|./*/h3|./*/h4')) > 1):
                selected = ancestor
                break
        if selected is not None:
            chosen.add(selected)
    # A full press-release paragraph may contain several useful clauses; dedupe
    # identical blocks but do not erase conflicting start evidence from another block.
    for node in chosen:
        text_value = _text(node)
        for container in node.iterancestors():
            if container.tag not in {'article', 'section', 'div', 'li', 'tr', 'main', 'body'}:
                continue
            headings = [heading for heading in container.xpath(HEADING_XPATH) if _visible(heading)]
            if len(headings) == 1 and len(_text(container)) <= 6000:
                title = _text(headings[0])
                if title and title not in text_value:
                    text_value = title + ' ' + text_value
                break
            if headings or container.tag in {'article', 'li', 'tr', 'main', 'body'}:
                break
        semantic = []
        for clock in node.xpath('.//time[@datetime]|.//*[@itemprop="startDate"]'):
            if not _visible(clock):
                continue
            raw = clock.get('datetime') or clock.get('content')
            if not raw:
                continue
            local = _text(clock.getparent())
            # Publication timestamps often sit beside an earnings-call title.
            if _negative_labels(local, list(CALL_RE.finditer(local))) or clock.get('itemprop') in {'datePublished', 'dateModified', 'endDate'}:
                continue
            if not CALL_RE.search(local):
                local = text_value
            if _is_call_label(local):
                semantic.append({'@type': 'Event', 'name': local, 'startDate': raw})
        blocks.append({'text': text_value, 'semantic': semantic})
    for script in document.xpath('//script[@type="application/ld+json"]/text()'):
        blocks.append({'json': str(script)})
    # Some issuer responses are a single plain block with no HTML container.
    if not blocks and CALL_RE.search(_text(document)):
        blocks.append({'text': _text(document)})
    return '\n'.join(BLOCK_PREFIX + json.dumps(block, ensure_ascii=False) for block in blocks)


def _zone(label: str):
    normalized = _compact(label).upper()
    if normalized in FIXED_ZONES:
        return timezone(timedelta(hours=FIXED_ZONES[normalized])), normalized
    name = REGIONAL_ZONES.get(normalized, label)
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        return None, name


def _wall_clock(day: date, hour: int, minute: int, label: str) -> tuple[datetime, str] | None:
    zone, name = _zone(label)
    if zone is None or not 0 <= hour < 24 or not 0 <= minute < 60:
        return None
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
    if isinstance(zone, ZoneInfo):
        if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            return None
        if local.utcoffset() != local.replace(fold=1).utcoffset():
            return None
    return local, name


def _negative_labels(value: str, positives):
    return [negative for negative in NEGATIVE_RE.finditer(value)
            if not any(positive.start() <= negative.start() and negative.end() <= positive.end()
                       for positive in positives)]


def _is_call_label(value: str) -> bool:
    positives = list(CALL_RE.finditer(value))
    return bool(positives) and not _negative_labels(value, positives) and not _non_earnings_event(value)


def _belongs_to_call(clause: str, start: int, end: int) -> bool:
    positives = list(CALL_RE.finditer(clause))
    negatives = _negative_labels(clause, positives)
    def distance(match):
        return max(start - match.end(), match.start() - end, 0)
    preceding = [m for m in positives + negatives if m.end() <= start]
    if preceding:
        latest = max(preceding, key=lambda m: m.end())
        if latest not in positives or distance(latest) > 320:
            return False
        # "Prepared remarks webcast" and "replay webcast" are not starts.
        label_prefix = clause[max(0, latest.start() - 35):latest.end()]
        if re.search(r'prepared\s+remarks|replay|pre[-\s]?recorded', label_prefix, re.I):
            return False
        return True
    return bool(positives) and min(map(distance, positives)) <= 180 and (
        not negatives or min(map(distance, positives)) < min(map(distance, negatives)))


def _scope_clauses(block: str) -> list[str]:
    """Keep an issuer's legal-name abbreviation attached to its event title.

    Splitting 'NIKE Inc. Earnings Call' drops the company from the very clock
    evidence whose provider identity must be checked. This only changes a
    sentence boundary inside the already isolated event scope.
    """
    value = _compact(block)
    clauses, start = [], 0
    for boundary in re.finditer(r'[;!?]\s*|(?<![aApP]\.[mM])\.\s+(?=[A-Z])', value):
        if boundary.group().startswith('.') and re.search(
                r'\b(?:inc|corp|co|ltd|plc)$', value[:boundary.start()], re.I):
            continue
        clauses.append(value[start:boundary.start()])
        start = boundary.end()
    clauses.append(value[start:])
    return clauses


def _split_json(value: str) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    prose: list[str] = []
    def visit(item):
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            title = str(item.get('name') or item.get('headline') or '')
            raw_types = item.get('@type', [])
            types = raw_types if isinstance(raw_types, list) else [raw_types]
            event_type = any(str(t).rsplit('/', 1)[-1].lower().endswith('event') for t in types)
            if item.get('startDate') and (event_type or not raw_types) and _is_call_label(title):
                records.append(item)
            for key in ('articleBody', 'body', 'description'):
                if isinstance(item.get(key), str):
                    # Keep an event description in its named event, including a
                    # non-earnings title that must not lend its clock to a call.
                    prose.append((title + ' ' if event_type and title else '') + item[key])
            for child in item.values():
                if isinstance(child, (list, dict)):
                    visit(child)
    decoder = json.JSONDecoder()
    remaining: list[str] = []
    cursor = 0
    for opening in re.finditer(r'[\[{]', value):
        start = opening.start()
        if start < cursor:
            continue
        try:
            parsed, end = decoder.raw_decode(value, start)
        except (ValueError, RecursionError):
            continue
        remaining.append(value[cursor:start])
        remaining.append('\n\n')
        visit(parsed)
        cursor = end
    remaining.append(value[cursor:])
    return records, ''.join(remaining) + '\n\n' + '\n\n'.join(prose)


def _ical_records(value: str) -> list[tuple[datetime, str, str]]:
    """Only concrete DTSTART from bounded VEVENT; no timezone/recurrence guesses."""
    if len(value) > 65536:
        return []
    unfolded = re.sub(r'\r?\n[ \t]', '', value)
    result = []
    for block in re.findall(r'BEGIN:VEVENT\s*\r?\n(.*?)END:VEVENT', unfolded, re.S | re.I)[:100]:
        fields = {}
        for line in block.splitlines():
            head, colon, content = line.partition(':')
            if colon:
                fields[head.upper().split(';', 1)[0]] = (head, content.strip())
        summary = fields.get('SUMMARY', ('', ''))[1]
        if (not _is_call_label(summary) or 'RRULE' in fields
                or fields.get('STATUS', ('', ''))[1].upper() == 'CANCELLED'):
            continue
        head, raw = fields.get('DTSTART', ('', ''))
        if 'VALUE=DATE' in head.upper() or not re.fullmatch(r'\d{8}T\d{6}Z?', raw):
            continue
        try:
            naive = datetime.strptime(raw.rstrip('Z'), '%Y%m%dT%H%M%S')
        except ValueError:
            continue
        if raw.endswith('Z'):
            local, name = naive.replace(tzinfo=timezone.utc), 'UTC'
        else:
            tzmatch = re.search(r'(?:^|;)TZID=(?:"([^"]+)"|([^;]+))', head, re.I)
            if not tzmatch:
                continue
            parsed = _wall_clock(naive.date(), naive.hour, naive.minute, tzmatch.group(1) or tzmatch.group(2))
            if parsed is None:
                continue
            local, name = parsed
            local = local.replace(second=naive.second)
        result.append((local, name, f'{summary} {head}:{raw}'))
    return result


def parse_call_times(text: str | bytes, expected_date: date, *, allow_date_shift: bool = False,
                     grace_days: int = 2, expected_fiscal_year: int | None = None,
                     expected_fiscal_quarter: str | None = None,
                     authenticated_provider: bool = False) -> CallTimeResult:
    """Return exact starts only when explicit call/date/zone evidence agrees.

    `allow_date_shift` is for callers that already proved the same issuer event;
    this parser cannot authenticate an event merely from a nearby calendar date.
    Expected fiscal identity is applied to each event scope before clocks and
    unavailable status are combined; a page-wide identity is never inherited
    by a different fiscal event or a non-earnings webcast.
    """
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')
    value = html_lib.unescape(str(text or ''))
    if len(value) > MAX_DOCUMENT_CHARS:
        return CallTimeResult()
    candidates: dict[datetime, CallTimeCandidate] = {}
    def scope_allows_shift(scope: str, evidence: str | None = None) -> bool:
        if not allow_date_shift:
            return False
        if not expected_fiscal_year and not expected_fiscal_quarter:
            # The caller may authenticate one immutable event URL without a
            # printed fiscal period. Unrelated event types are filtered above.
            return True
        for context in (evidence, scope):
            if not context:
                continue
            year, quarter = fiscal_period(context)
            if (year and quarter and str(year) == str(expected_fiscal_year)
                    and quarter == str(expected_fiscal_quarter).upper()
                    and len(_event_dates(context, expected_date)) <= 1):
                return True
        return False

    def add(local: datetime, zone_name: str, evidence: str, scope: str | None = None):
        if local.tzinfo is None or local.utcoffset() is None:
            return
        if (abs((local.date() - expected_date).days) > max(0, grace_days)
                and not scope_allows_shift(scope or evidence, evidence)):
            return
        utc = local.astimezone(timezone.utc)
        candidates.setdefault(utc, CallTimeCandidate(local.date(), utc, zone_name, _compact(evidence)[:600]))
    if 'BEGIN:VCALENDAR' in value or 'BEGIN:VEVENT' in value:
        for local, zone, evidence in _ical_records(value):
            if _allowed_event_scope(evidence, expected_fiscal_year, expected_fiscal_quarter):
                add(local, zone, evidence)
        ordered = tuple(candidates[k] for k in sorted(candidates))
        return CallTimeResult(ordered, len(ordered) > 1)
    if re.search(r'<(?:html|article|section|div|p|h[1-6]|script|time)\b', value, re.I):
        try:
            value = schedule_time_text(html.fromstring(value))
        except (ValueError, TypeError):
            return CallTimeResult()
    blocks: list[str] = []
    records: list[dict[str, Any]] = []
    if value.startswith(BLOCK_PREFIX):
        for line in value.splitlines():
            if not line.startswith(BLOCK_PREFIX):
                continue
            try:
                block = json.loads(line[len(BLOCK_PREFIX):])
            except (ValueError, RecursionError):
                continue
            blocks.append(str(block.get('text') or ''))
            if block.get('json'):
                found, prose = _split_json(str(block['json']))
                records.extend(found)
                blocks.append(prose)
            for semantic in block.get('semantic', []):
                if isinstance(semantic, dict) and _is_call_label(str(semantic.get('name') or '')):
                    records.append({**semantic, '_scope_text': str(block.get('text') or '')})
    else:
        records, prose = _split_json(value)
        blocks.extend(re.split(r'\n\s*\n', prose))
    unavailable: set[str] = set()
    for record in records:
        record_title = str(record.get('name') or record.get('headline') or '')
        record_scope = str(record.get('_scope_text') or record_title)
        if (not _allowed_event_scope(record_title, expected_fiscal_year, expected_fiscal_quarter)
                or not _allowed_event_scope(record_scope, expected_fiscal_year, expected_fiscal_quarter)):
            continue
        try:
            local = datetime.fromisoformat(str(record['startDate']).replace('Z', '+00:00'))
        except (ValueError, KeyError):
            continue
        if (abs((local.date() - expected_date).days) > max(0, grace_days)
                and not scope_allows_shift(record_scope, record_title)):
            continue
        event_status = str(record.get('eventStatus') or '').lower()
        if event_status.endswith('eventcancelled'):
            unavailable.add('cancelled')
            continue
        if event_status.endswith('eventpostponed'):
            unavailable.add('postponed')
            continue
        add(local, str(local.tzinfo or ''), json.dumps({
            'name': record.get('name'), 'startDate': record['startDate']}, ensure_ascii=False), record_scope)
    for block in blocks:
        block_allowed = _allowed_event_scope(block, expected_fiscal_year, expected_fiscal_quarter)
        scoped_dates = _event_dates(block, expected_date)
        # Serialized snapshots can still contain several event sentences. Scope
        # filtering is repeated per clause before aggregating clocks or status.
        clauses = _scope_clauses(block)
        previous_call_clause = None
        for clause in clauses:
            if not CALL_RE.search(clause):
                # A semicolon can separate the status from its call label:
                # 'Earnings call ...; time to be announced'. Only an immediate
                # continuation of an eligible call may inherit that label.
                if (previous_call_clause and UNAVAILABLE_RE.search(clause)
                        and _allowed_event_scope(clause, expected_fiscal_year, expected_fiscal_quarter)):
                    clause = previous_call_clause + '; ' + clause
                else:
                    previous_call_clause = None
                    continue
            previous_call_clause = None
            if not _allowed_event_scope(clause, expected_fiscal_year, expected_fiscal_quarter):
                continue
            year, quarter = fiscal_period(clause)
            explicit_target = bool(year and quarter and str(year) == str(expected_fiscal_year)
                                   and quarter == str(expected_fiscal_quarter).upper())
            if not block_allowed and not explicit_target:
                continue
            previous_call_clause = clause
            clause_dates = _event_dates(clause, expected_date)
            status_dates = clause_dates or (scoped_dates if block_allowed else set())
            date_matches = any(abs((day - expected_date).days) <= max(0, grace_days) for day in status_dates)
            if scope_allows_shift(block, clause) or date_matches:
                for marker in UNAVAILABLE_RE.finditer(clause):
                    if _belongs_to_call(clause, marker.start(), marker.end()):
                        token = marker.group().lower()
                        unavailable.add('cancelled' if token in {'cancelled', 'canceled'} else 'postponed' if token == 'postponed' else 'time_tbd')
            dates: list[tuple[int, int, date]] = []
            for match in (*DATE_RE.finditer(clause), *DMY_DATE_RE.finditer(clause)):
                if non_event_date_reason(clause, *match.span()):
                    continue
                try:
                    day = date(int(match.group('year') or expected_date.year),
                               MONTHS[match.group('month')[:3].lower()], int(match.group('day')))
                    dates.append((match.start(), match.end(), day))
                except ValueError:
                    pass
            for match in ISO_DATE_RE.finditer(clause):
                if non_event_date_reason(clause, *match.span()):
                    continue
                try:
                    dates.append((match.start(), match.end(), date(*map(int, match.groups()))))
                except ValueError:
                    pass
            for match in ISO_TIME_RE.finditer(clause):
                if (not non_event_date_reason(clause, *match.span())
                        and _belongs_to_call(clause, match.start(), match.end())):
                    try:
                        local = datetime.fromisoformat(match.group().replace('Z', '+00:00'))
                    except ValueError:
                        continue
                    add(local, str(local.tzinfo or ''), clause, block)
            for match in CLOCK_RE.finditer(clause):
                if not _belongs_to_call(clause, match.start(), match.end()):
                    continue
                eligible = {day for start, end, day in dates if _belongs_to_call(clause, start, end)}
                if len(eligible) != 1:
                    continue
                hour, minute = int(match.group('hour')), int(match.group('minute') or 0)
                if not 1 <= hour <= 12:
                    continue
                hour = hour % 12 + (12 if match.group('meridiem').lower().startswith('p') else 0)
                local = _wall_clock(next(iter(eligible)), hour, minute, match.group('timezone'))
                if local:
                    add(*local, clause, block)
    ordered = tuple(candidates[k] for k in sorted(candidates))
    reason = 'cancelled' if 'cancelled' in unavailable else next(iter(sorted(unavailable)), None)
    if not ordered and not reason and authenticated_provider:
        # Some validated webcast registration pages label the event only
        # 'Fourth Quarter Fiscal 2026 Earnings'. This narrow fallback requires
        # the caller's provider-route proof, the full matching fiscal identity,
        # one exact event date and no release/replay/other-event wording.
        label = _compact(value)
        year, quarter = fiscal_period(label)
        if (len(label) <= 6000 and '<' not in label and not CALL_RE.search(label)
                and re.search(r'\bearnings\b', label, re.I)
                and not NEGATIVE_RE.search(label) and not _non_earnings_event(label)
                and expected_fiscal_year and expected_fiscal_quarter
                and str(year) == str(expected_fiscal_year)
                and quarter == str(expected_fiscal_quarter).upper()
                and _event_dates(label, expected_date) == {expected_date}):
            for match in CLOCK_RE.finditer(label):
                hour, minute = int(match.group('hour')), int(match.group('minute') or 0)
                if not 1 <= hour <= 12:
                    continue
                hour = hour % 12 + (12 if match.group('meridiem').lower().startswith('p') else 0)
                local = _wall_clock(expected_date, hour, minute, match.group('timezone'))
                if local:
                    add(*local, label, label)
            ordered = tuple(candidates[k] for k in sorted(candidates))
    return CallTimeResult(ordered, len(ordered) > 1, reason)
