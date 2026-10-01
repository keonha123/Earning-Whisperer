"""Redact credentials from persisted diagnostics."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


SENSITIVE_URL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "auth",
        "authorization",
        "code",
        "id_token",
        "jwt",
        "password",
        "passwd",
        "refresh_token",
        "session",
        "sig",
        "signature",
        "state",
        "token",
    }
)


_URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s<>\]\\\"']+", re.IGNORECASE)


def redact_sensitive_url(url: str | None) -> str | None:
    """Mask credential-bearing query values before URLs enter audit storage."""
    if not url:
        return url
    value = str(url)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return value
    safe_query = urlencode(
        [
            (
                key,
                "[REDACTED]" if key.lower() in SENSITIVE_URL_QUERY_KEYS else item,
            )
            for key, item in pairs
        ]
    )
    return urlunparse(parsed._replace(query=safe_query))


def redact_sensitive_text(value: str | None) -> str | None:
    """Redact sensitive URL parameters embedded in browser output and errors."""
    if value is None:
        return None

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:)":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        return (redact_sensitive_url(raw) or raw) + trailing

    return _URL_IN_TEXT_PATTERN.sub(replace, str(value))
