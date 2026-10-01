"""Issuer-linked event routes. URL words alone never authenticate a webcast."""
from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

EARNINGS = re.compile(r'\b(?:earnings?|financial\s+results?|quarter(?:ly)?|results\s+call)\b', re.I)
PLAYBACK = re.compile(r'\b(?:webcast|listen|watch|join|register|audio|conference\s+call|earnings\s+call|results\s+call|live\s+stream)\b', re.I)
NON_PLAYBACK = re.compile(r'\b(?:transcript|presentation\s+(?:slides|pdf)|press\s+release|news\s+release|download|calendar|privacy|cookie|terms)\b', re.I)
ASSET = re.compile(r'\.(?:pdf|ics|csv|docx?|xlsx?|pptx?|zip|css|js|map|png|jpe?g|gif|svg|ico|webp|avif|bmp|woff2?|ttf)(?:$|[?#])', re.I)
TRACKER = re.compile(r'(?:^|[./_-])(?:doubleclick|googleadservices|googlesyndication|adservice|adserver|adnxs|adsystem|advertising|tracking|analytics|pixel)(?:[./_-]|$)|(?:^|\.)ads\.', re.I)
QUARTER = re.compile(r'\b(?:Q([1-4])|([1-4])(?:st|nd|rd|th)?\s*(?:fiscal\s+)?(?:qtr|quarter)|(?:(first|second|third|fourth)\s+(?:fiscal\s+)?quarter))\b', re.I)
YEAR = re.compile(r'\b(?:FY\s*)?(20\d{2})\b', re.I)
PROOF_PREFIX = 'issuer-route-v2:'
EVENT_NAVIGATION = re.compile(
    r'^(?:(?:view|see|browse|back\s+to)\s+)?(?:(?:all|past|previous|next|upcoming|future|archived?)\s+)?'
    r'(?:events?(?:\s*(?:&|and)\s+presentations?)?(?:\s+(?:list|calendar|view|archive))?|calendar|today|list|month|day)'
    r'(?:\s+view)?[\s»‹›←→-]*$', re.I)


def is_event_navigation(url, label=''):
    """A calendar control can lead to discovery, but cannot identify one event."""
    label = re.sub(r'\s+', ' ', str(label or '')).strip()
    if EVENT_NAVIGATION.fullmatch(label):
        return True
    parsed = urlparse(str(url or ''))
    query = {key.lower(): value for key, value in parse_qs(parsed.query).items()}
    if (any(value.lower() in {'past', 'list', 'month', 'day', 'upcoming', 'week', 'photo', 'map'}
            for value in query.get('eventdisplay', [])) or 'tribe-bar-date' in query):
        return True
    return bool(re.search(r'/(?:events?|calendar)/(?:list|month|today|day)/?$', parsed.path, re.I))


def issuer_listing_fallbacks(url):
    """Bounded same-origin parents of an event-detail path, without search.

    These are navigation hints only: each returned page must establish fresh
    event/date/link evidence before it can be stored or used for playback.
    """
    value = normalize_route(str(url or ''), url)
    if not value:
        return []
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split('/') if part]
    for index, part in enumerate(parts):
        if part.lower() not in {'event-details', 'event-detail', 'eventdetails'}:
            continue
        if index == 0:
            return []
        parent = '/' + '/'.join(parts[:index]) + '/'
        return [urlunparse(parsed._replace(path=parent, query='', fragment=''))]
    return []


def normalize_route(base_url, raw):
    value = html_lib.unescape(str(raw or '').strip()).replace('\\/', '/').replace('\\u0026', '&')
    if not value or value.lower().startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
        return None
    value = urljoin(base_url, value)
    p = urlparse(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        return None
    if ASSET.search(p.path) or TRACKER.search((p.hostname or '') + p.path):
        return None
    return urlunparse(p._replace(fragment=''))


def fiscal_period(text):
    """Read an explicitly printed fiscal period, never infer it from the date."""
    text = re.sub(r'\b([1-4])Q\b', r'Q\1', str(text or ''), flags=re.I)
    q = QUARTER.search(text)
    if not q:
        return None, None
    number = q.group(1) or q.group(2) or {'first':'1','second':'2','third':'3','fourth':'4'}[q.group(3).lower()]
    after = text[q.end():q.end()+45]
    before = text[max(0,q.start()-25):q.start()]
    year_match = re.match(r'^[\s,:-]*(?:of\s+)?(?:fiscal\s*|FY\s*)?(20\d{2})\b', after, re.I)
    if year_match is None:
        year_match = re.search(r'\b(?:FY\s*|fiscal\s*)?(20\d{2})[\s,:-]*$', before, re.I)
    return (int(year_match.group(1)) if year_match else None), f'Q{number}'



def expected_period(call):
    # call_year/quarter are calendar buckets in legacy rows and are not proof.
    return call.get('verified_fiscal_year'), call.get('verified_fiscal_quarter')


def period_mismatch(call, text):
    year, quarter = fiscal_period(text)
    expected_year, expected_quarter = expected_period(call)
    return bool((expected_year and year and int(expected_year) != year) or
                (expected_quarter and quarter and str(expected_quarter).upper() != quarter))


def visible_text(node):
    values = node.xpath('.//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::nav) and not(ancestor::footer) and not(ancestor::*[@hidden]) and not(ancestor::*[@aria-hidden="true"])]')
    values = [str(value) for value in values if not any(
        re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', parent.get('style','') or '',re.I)
        for parent in (value.getparent(), *value.getparent().iterancestors()) if isinstance(parent.tag,str))]
    return re.sub(r'\s+', ' ', ' '.join(values)).strip()


def scope_text(node):
    text = visible_text(node)
    stamps = [value for value in node.xpath('.//time[not(@itemprop="datePublished") and not(@itemprop="dateModified")]/@datetime')
              if re.match(r'^20\d{2}-\d{2}-\d{2}',value)]
    return text + (' ' + ' '.join(stamps) if stamps else '')


def _multiple_events(node):
    text = visible_text(node)
    quarters = {m.group(1) or m.group(2) or {'first':'1','second':'2','third':'3','fourth':'4'}[m.group(3).lower()] for m in QUARTER.finditer(text)}
    if len(quarters) > 1:
        return True
    headings = [visible_text(n) for n in node.xpath('.//h1|.//h2|.//h3|.//h4|.//*[@role="heading"]')]
    return sum(bool(EARNINGS.search(t) or re.search(
        r'\b(?:investor\s+day|capital\s+markets?\s+day|annual\s+(?:general\s+)?meeting)\b', t, re.I))
        for t in headings) > 1


def event_scope(element):
    """Stop at a card boundary; never borrow an adjacent card's date/title."""
    chain = (element, *element.iterancestors())
    if any(node.tag in {'nav','footer','aside','head','script','style'} or node.get('role') == 'navigation'
           or node.get('hidden') is not None or node.get('aria-hidden') == 'true'
           or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', node.get('style',''), re.I)
           for node in chain):
        return None
    for node in chain:
        if not isinstance(node.tag, str) or node.tag in {'nav', 'footer', 'aside', 'head'}:
            return None
        if node.get('hidden') is not None or node.get('aria-hidden') == 'true':
            return None
        text = visible_text(node)
        if _multiple_events(node):
            return None
        has_date = bool(re.search(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*|20\d{2}-\d{2}-\d{2}', text, re.I) or node.xpath('.//time[@datetime]'))
        if EARNINGS.search(text) and has_date and len(text) <= 4500:
            return node
        if node.tag in {'article', 'li', 'tr', 'section', 'body', 'html'}:
            return None
    return None


def scoped_candidates(document, base_url):
    found = []
    seen = set()
    attributes = ('href', 'src', 'data-src', 'data-url', 'data-href', 'data-event-url', 'data-webcast-url')
    for element in document.xpath('//*'):
        if element.tag in {'script','style','link','img','meta'} or not any(a in element.attrib for a in attributes):
            continue
        scope = event_scope(element)
        if scope is None:
            continue
        context = scope_text(scope)
        label = ' '.join((visible_text(element), element.get('aria-label',''), element.get('title',''))).strip()
        for attribute in attributes:
            if attribute not in element.attrib:
                continue
            url = normalize_route(base_url, element.get(attribute))
            if not url:
                continue
            if any(is_event_navigation(url, value) for value in
                   (visible_text(element), element.get('aria-label', ''), element.get('title', ''))):
                continue
            # Generic embedded advertisements must not borrow the event title.
            direct_action = bool(PLAYBACK.search(label)) or attribute == 'data-webcast-url'
            if attribute in {'src', 'data-src'} and not direct_action:
                continue
            if NON_PLAYBACK.search(label) and not re.search(r'\b(?:webcast|listen|watch|join)\b', label, re.I):
                continue
            key = (url, document.getroottree().getpath(scope))
            if key in seen:
                continue
            seen.add(key)
            found.append({'url':url, 'label':label, 'context':context, 'attribute':attribute,
                          'scope':key[1], 'playback':direct_action})
    # Arbitrary JS URL strings intentionally do not supply event/link proof.
    return found


def route_proof(*, ticker, day, issuer_url, event_url, webcast_url, fiscal_year=None, fiscal_quarter=None, event_type="earnings_call"):
    payload = {'version':2, 'ticker':str(ticker or '').upper(), 'date':day.isoformat(),
               'issuer_url':issuer_url, 'event_url':event_url, 'webcast_url':webcast_url,
               'fiscal_year':fiscal_year, 'fiscal_quarter':fiscal_quarter, 'event_type':event_type, 'relation':'same_event_container'}
    return PROOF_PREFIX + json.dumps(payload, separators=(',', ':'), sort_keys=True)


def read_route_proof(evidence):
    pos = str(evidence or '').find(PROOF_PREFIX)
    if pos < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(str(evidence)[pos+len(PROOF_PREFIX):])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get('version') == 2 else None


def stored_event_kind_conflict(evidence):
    """Recheck old scoped evidence with today's event-kind rules.

    Typed legacy metadata is not stronger than an explicit non-earnings title.
    Strip its JSON first so a URL containing ``earnings-call`` cannot mask a
    contradictory visible title. Mixed prose with a real earnings call remains
    inconclusive rather than invalidating an otherwise valid schedule.
    """
    value = str(evidence or '')
    pos = value.find(PROOF_PREFIX)
    if pos >= 0:
        try:
            _, end = json.JSONDecoder().raw_decode(value[pos + len(PROOF_PREFIX):])
        except (ValueError, TypeError):
            pass
        else:
            value = value[:pos] + value[pos + len(PROOF_PREFIX) + end:]
    from .call_times import _non_earnings_event
    return _non_earnings_event(html_lib.unescape(value))
