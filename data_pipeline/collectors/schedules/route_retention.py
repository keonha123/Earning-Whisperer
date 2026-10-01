"""Preserve an observed route without inventing a new observation timestamp."""
from datetime import date, datetime
import re
from .event_routes import read_route_proof, stored_event_kind_conflict

ROUTE_FIELDS = ('event_url', 'webcast_url', 'schedule_evidence',
                'schedule_discovery_fingerprint', 'schedule_discovery_checked_at')


def event_day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value or '')[:10]).isoformat()
    except ValueError:
        return None


def authenticated_route(row):
    """Structural authentication only; callers still enforce the original TTL."""
    proof = read_route_proof(row.get('schedule_evidence'))
    if (not proof or stored_event_kind_conflict(row.get('schedule_evidence'))
            or proof.get('event_type') != 'earnings_call'
            or proof.get('relation') != 'same_event_container'
            or str(proof.get('ticker') or '').upper() != str(row.get('ticker') or '').upper()
            or proof.get('date') != event_day(row.get('webcast_date') or row.get('earning_at'))
            or not row.get('webcast_url') or proof.get('webcast_url') != row.get('webcast_url')
            or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('schedule_discovery_fingerprint') or ''))
            or not row.get('schedule_discovery_checked_at')):
        return None
    for key, stored in (('fiscal_year', 'verified_fiscal_year'), ('fiscal_quarter', 'verified_fiscal_quarter')):
        if proof.get(key) and row.get(stored) and str(proof[key]).upper() != str(row[stored]).upper():
            return None
    return proof


def retained_route_fields(row, changes, identity=None):
    """Missing provider on a same-event weak observation is not a withdrawal."""
    proof = authenticated_route(row)
    if (not proof or changes.get('webcast_url')
            or stored_event_kind_conflict(changes.get('schedule_evidence'))
            or event_day(changes.get('webcast_date')) != event_day(row.get('webcast_date') or row.get('earning_at'))):
        return {}
    identity = identity or {}
    for incoming, old in ((identity.get('fiscal_year'), row.get('verified_fiscal_year')),
                          (identity.get('fiscal_quarter'), row.get('verified_fiscal_quarter'))):
        if incoming and old and str(incoming).upper() != str(old).upper():
            return {}
    same_detail = bool(changes.get('event_url') and changes.get('event_url') == row.get('event_url')
                       and changes.get('event_url') in {proof.get('event_url'), proof.get('issuer_url')})
    same_period = bool(identity.get('identity_verified') is True
        and identity.get('event_type') == 'earnings_call'
        and identity.get('fiscal_year') and identity.get('fiscal_quarter')
        and str(identity['fiscal_year']) == str(row.get('verified_fiscal_year'))
        and identity['fiscal_quarter'] == row.get('verified_fiscal_quarter'))
    if not (same_detail or same_period):
        return {}
    # Preserve the old proof and checked_at as one unit, including expired proof.
    # Keeping a stale address available for rediscovery never makes it reusable.
    return {key: row.get(key) for key in ROUTE_FIELDS}
