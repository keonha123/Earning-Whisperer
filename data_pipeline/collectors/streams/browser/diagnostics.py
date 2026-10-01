"""Opt-in, bounded browser evidence. Observes controls without changing the page."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid
from data_pipeline.live_telemetry import emit_live_event


def enabled(agent: Any) -> bool:
    if os.getenv("WEBCAST_LIVE_DIAGNOSTICS", "").lower() not in {"1", "true", "yes", "on"}:
        return False
    tickers = {part.strip().upper() for part in os.getenv("WEBCAST_LIVE_DIAGNOSTICS_TICKERS", "").split(",") if part.strip()}
    return not tickers or str(getattr(agent, "ticker", "")).upper() in tickers


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            return parsed.scheme + ":" if parsed.scheme else ""
        return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
    except ValueError:
        return "[invalid URL]"


def _scrub(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, str):
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", value)
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    return value


_OBSERVE = """() => {
  const visible = e => { const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
  const compact = v => String(v || '').replace(/\\s+/g, ' ').trim().slice(0, 240);
  const safeUrl = v => {try { const u=new URL(v,location.href);
    return ['http:','https:'].includes(u.protocol) ? u.origin+u.pathname : u.protocol;
  } catch {return '';}};
  const roots=[document];
  for(let i=0;i<roots.length && roots.length<20;i++) {
    for(const e of roots[i].querySelectorAll('*')) {if(e.shadowRoot && roots.length<20) roots.push(e.shadowRoot);}
  }
  const all = selector => roots.flatMap(root=>Array.from(root.querySelectorAll(selector)));
  return {
    controls: all('button,a,[role="button"],[role="tab"]').filter(visible).slice(0,100).map(e=>({
      tag:e.tagName.toLowerCase(),role:e.getAttribute('role') || '',
      text:compact(e.innerText),label:compact(e.getAttribute('aria-label')),
      href:e.hasAttribute('href') ? safeUrl(e.getAttribute('href')) : '',
      disabled:Boolean(e.disabled || e.getAttribute('aria-disabled')==='true')})),
    fields:all('input,textarea,select,[contenteditable="true"]').filter(visible).slice(0,60).map(e=>({
      tag:e.tagName.toLowerCase(),type:e.type || '',name:compact(e.name),
      label:compact(e.getAttribute('aria-label') || Array.from(e.labels || []).map(l=>l.innerText).join(' ')),
      required:Boolean(e.required),disabled:Boolean(e.disabled),
      invalid:Boolean(e.validity && !e.validity.valid),
      value_missing:Boolean(e.validity && e.validity.valueMissing),
      checked:['checkbox','radio'].includes(e.type) ? Boolean(e.checked) : null})),
    media:all('audio,video').slice(0,15).map(e=>({
      tag:e.tagName.toLowerCase(),paused:Boolean(e.paused),ended:Boolean(e.ended),
      current_time:Number(e.currentTime),muted:Boolean(e.muted),volume:Number(e.volume),
      ready_state:Number(e.readyState),network_state:Number(e.networkState),
      error_code:e.error ? e.error.code : null,source:safeUrl(e.currentSrc || e.src)}))
  };
}"""


async def capture_diagnostics(agent: Any, target: Any, phase: str) -> str | None:
    """Save metadata within three seconds; diagnostic failures never alter capture."""
    if not enabled(agent) or target is None:
        return None
    try:
        return await asyncio.wait_for(_capture(agent, target, phase), timeout=3.0)
    except (Exception, asyncio.TimeoutError):
        return None


async def _capture(agent: Any, target: Any, phase: str) -> str:
    pages = list(target.pages) if hasattr(target, "pages") else [target]
    profile = getattr(agent, "profile", None)
    secrets = sorted({str(getattr(profile, key, "")) for key in (
        "email", "password", "first_name", "last_name", "company", "phone_number",
        "q4_email", "q4_password", "q4_first_name", "q4_last_name",
    ) if len(str(getattr(profile, key, ""))) >= 3}, key=len, reverse=True)
    ticker = re.sub(r"[^A-Z0-9_-]", "", str(getattr(agent, "ticker", "UNKNOWN")).upper())[:16]
    root = Path(os.getenv("WEBCAST_LIVE_DIAGNOSTICS_DIR", str(Path(__file__).resolve().parents[3] / ".runtime" / "live-diagnostics")))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    stamp = datetime.now(timezone.utc)
    prefix = root / f"{ticker}-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {"call_id": os.getenv("WEBCAST_CALL_DB_ID", ""),
                              "schedule_revision": os.getenv("WEBCAST_SCHEDULE_REVISION", ""),
                              "attempt_id": os.getenv("WEBCAST_ATTEMPT_ID", ""),
                              "capture_session_id": os.getenv("STT_CAPTURE_SESSION_ID", ""),
                              "ticker": ticker, "timestamp": stamp.isoformat(), "phase": phase, "pages": [],
                              "playback_observations": list(getattr(agent, "_playback_observations", []) or [])[-10:]}
    for page in pages[:3]:
        entry: dict[str, Any] = {"url": _safe_url(str(page.url)), "frames": []}
        for frame in list(page.frames)[:6]:
            try:
                data = await asyncio.wait_for(frame.evaluate(_OBSERVE), timeout=0.4)
                entry["frames"].append({"url": _safe_url(str(frame.url)), **data})
            except Exception:
                entry["frames"].append({"url": _safe_url(str(frame.url)), "observation_unavailable": True})
        payload["pages"].append(entry)
    path = prefix.with_suffix(".json")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(_scrub(payload, secrets), stream, ensure_ascii=False, indent=2)
    print(f"[{ticker}] LIVE_DIAGNOSTICS phase={phase} path={path}", flush=True)
    stage = "registration" if phase.startswith("registration") else "playback" if phase.startswith(("playback", "waiting")) else "discovery"
    emit_live_event(stage, "diagnostic_saved", ticker=ticker, phase=phase, artifact_path=str(path))
    # Persist JSON first so a screenshot timeout still leaves the useful state.
    if os.getenv("WEBCAST_LIVE_DIAGNOSTICS_SCREENSHOT", "false").lower() == "true" and pages:
        page = pages[-1]
        masks = [frame.locator('input,textarea,select,[contenteditable="true"]') for frame in page.frames]
        for frame in page.frames:
            masks.extend(frame.get_by_text(secret, exact=False) for secret in secrets)
        try:
            screenshot = await page.screenshot(type="jpeg", quality=55, timeout=700,
                                              full_page=False, mask=masks)
            with os.fdopen(os.open(prefix.with_suffix(".jpg"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(screenshot)
        except Exception:
            pass
    return str(path)
