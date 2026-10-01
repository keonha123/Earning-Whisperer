"""Keep supervised live browsers alive and report evidence-backed source endings."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit
from data_pipeline.live_telemetry import emit_live_event


ENDED_TEXT = re.compile(
    r"^(?:(?:this|the)\s+)?(?:live\s+)?(?:webcast|webinar|event|earnings\s+call|conference\s+call|broadcast)"
    r"\s+(?:(?:has|have)\s+(?:now\s+)?)?(?:ended|concluded|finished)"
    r"(?:[.!:;,\s]|$)|^thank\s+you\s+for\s+(?:attending|joining)"
    r"[.!:\s]+(?:this|the)\s+(?:webcast|webinar|event|call)\s+has\s+(?:ended|concluded)",
    re.I,
)
Q4_ENDED_TEXT = re.compile(
    r"^broadcast\s+has\s+ended\s*[,.;:!]\s*thanks\s+for\s+watching[.!]?\s*$", re.I,
)
END_SURFACES = (
    "[role='alert'], [role='status'], [role='dialog'], [class*='modal' i], "
    "[data-event-status='ended'], [data-webcast-status='ended'], "
    "[data-event-state='ended'], [data-webcast-state='ended'], "
    "[class*='event-ended' i], [class*='webcast-ended' i], "
    "[class*='player' i] [class*='ended' i]"
)


def supervised_live(agent) -> bool:
    return agent.lifecycle == "live" and os.getenv("WEBCAST_SUPERVISED_LIVE", "").lower() in {
        "1", "true", "yes", "on",
    }


def read_current_termination(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        run_id = os.environ.get("WEBCAST_LIVE_RUN_ID", "")
        run_start = float(os.environ.get("WEBCAST_LIVE_RUN_STARTED_AT", "0"))
        created = float(value.get("created_at", 0))
        if (
            not isinstance(value, dict) or value.get("version") != 1
            or value.get("reason") not in {"event_ended", "source_lost"}
            or not math.isfinite(created) or not math.isfinite(run_start)
            or not run_id or value.get("run_id") != run_id
            or value.get("call_id") != os.environ.get("CALL_ID", "")
            or value.get("capture_session_id") != os.environ.get("STT_CAPTURE_SESSION_ID", os.environ.get("CALL_ID", ""))
            or created < run_start - 1 or created > time.time() + 5
        ):
            return None
        if value["reason"] == "event_ended":
            proof = value.get("event_identity")
            expected_ticker = os.environ.get("TICKER", "").upper()
            expected_date = os.environ.get("WEBCAST_TARGET_DATE", "")
            if (
                value.get("target_identity_verified") is not True
                or not isinstance(proof, dict) or proof.get("verified") is not True
                or not expected_ticker or str(proof.get("call_ticker") or "").upper() != expected_ticker
                or not expected_date or proof.get("target_date") != expected_date
                or not str(value.get("url") or "").strip()
                or not str(value.get("evidence") or "").strip()
            ):
                return None
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def write_termination(reason: str, *, verified: bool = False, evidence: str = "",
                      url: str = "", proof: dict | None = None) -> dict | None:
    configured = os.environ.get("WEBCAST_LIVE_TERMINATION_FILE", "")
    if not configured:
        return None
    path = Path(configured)
    value = {
        "version": 1, "reason": reason, "call_id": os.environ.get("CALL_ID", ""),
        "capture_session_id": os.environ.get("STT_CAPTURE_SESSION_ID", os.environ.get("CALL_ID", "")),
        "run_id": os.environ.get("WEBCAST_LIVE_RUN_ID", ""),
        "created_at": time.time(), "target_identity_verified": bool(verified),
        "evidence": evidence[:1000], "url": url, "event_identity": proof,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Both browser and supervisor may notice a terminal state on the same tick.
    # Serialize their check+replace so a late source-loss write cannot erase the
    # stronger current-event completion proof.
    lock_fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = read_current_termination(path)
        if existing and existing.get("reason") == "event_ended":
            return existing
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(value, output)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return value


def _end_provider_event_id(url: str) -> str | None:
    """Recognize Q4's event route for end evidence, without generalizing navigation."""
    from .navigation import provider_event_id
    known = provider_event_id(url)
    if known:
        return known
    parsed = urlsplit(url)
    if parsed.scheme in {"http", "https"} and parsed.hostname == "events.q4inc.com":
        match = re.fullmatch(r"/attendee/(\d+)(?:/guest)?/?", parsed.path)
        if match:
            return f"q4:{match.group(1)}"
    return None


async def current_event_end_evidence(agent, page: Any) -> str | None:
    """A visible current-event status is necessary; silence/media.ended is not."""
    if not await agent._validate_live_target_page(page):
        return None
    from ..webcast_learning import WebcastCandidate, candidate_identity_mismatch
    proof = getattr(agent, "live_target_proof", None) or {}
    expected_id = (proof.get("provider_event_id")
                   or _end_provider_event_id(str(proof.get("target_url") or ""))
                   or _end_provider_event_id(str(page.url)))
    current_id = _end_provider_event_id(str(page.url))
    if expected_id and current_id and expected_id != current_id:
        return None
    # An end banner in the outer page cannot close an event iframe still
    # playing. Unknown frames may veto completion, but never prove it.
    for frame in page.frames:
        try:
            if await frame.evaluate("""() => Array.from(document.querySelectorAll('audio,video'))
                .some(el => !el.paused && !el.ended && el.readyState >= 2)"""):
                return None
        except Exception:
            continue
    for frame in page.frames:
        # Embedded advertising/other-event frames cannot terminate this event.
        if frame is not page.main_frame:
            frame_id = _end_provider_event_id(str(frame.url))
            if not expected_id or frame_id != expected_id:
                continue
        try:
            elements = await frame.locator(END_SURFACES).element_handles()
            elements += await frame.locator(END_SURFACES).get_by_text(ENDED_TEXT).element_handles()
            # Known event-specific provider routes sometimes render a plain
            # heading rather than a role/status component.
            if expected_id:
                elements += await frame.get_by_text(ENDED_TEXT).element_handles()
            for element in elements:
                if not await element.is_visible():
                    continue
                row = await element.evaluate("""el => ({
                    text: (el.innerText || '').replace(/\\s+/g,' ').trim(),
                    navigation: !!el.closest('nav,aside,header,footer'),
                    scoped: /^(H1|H2)$/.test(el.tagName) || !!el.closest(
                        '[role="alert"],[role="status"],[role="dialog"],[class*="modal" i],' +
                        '[data-event-status="ended"],[data-webcast-status="ended"],' +
                        '[data-event-state="ended"],[data-webcast-state="ended"],' +
                        '[class*="player" i],[class*="event-ended" i],[class*="webcast-ended" i]'),
                    eventId: el.closest('[data-event-id]')?.getAttribute('data-event-id') || '',
                    otherContent: !!el.closest('article,a,[role="link"]')
                })""")
                text = row["text"]
                # Q4 renders this exact end notice without a semantic status
                # role. Only the proven event's main route can supply this
                # fallback; generic paragraphs and other-event cards cannot.
                provider_scoped = bool(
                    expected_id and str(expected_id).startswith("q4:")
                    and current_id == expected_id and frame is page.main_frame
                    and not row["otherContent"] and Q4_ENDED_TEXT.fullmatch(text)
                )
                if row["navigation"] or not (row["scoped"] or provider_scoped) or len(text) > 1000 or not ENDED_TEXT.search(text):
                    continue
                if row["eventId"] and (not expected_id or row["eventId"] != str(expected_id).split(":", 1)[-1]):
                    continue
                candidate = WebcastCandidate(
                    "live-end", (), None, text, "", "", None, "status", {},
                )
                if candidate_identity_mismatch(candidate, target_ticker=agent.ticker,
                                               target_date=agent.target_date):
                    continue
                return text
        except Exception:
            continue
    return None


class PlaybackProgress:
    """Detect loss of clock progress; neither silence nor a stalled clock is an end."""
    def __init__(self, now: float, warning_seconds: float = 45):
        self.last_progress = now
        self.warning_seconds = warning_seconds
        self.previous: dict[str, float] = {}
        self.recovery_count = 0
        self.last_recovery = float("-inf")

    def observe(self, samples: list[dict], now: float, *, waiting: bool = False) -> dict:
        advancing = False
        current = {}
        for row in samples:
            key = str(row["key"])
            clock = float(row.get("current_time") or 0)
            current[key] = clock
            previous = self.previous.get(key)
            if (previous is not None and clock - previous > .05
                    and not row.get("paused") and not row.get("ended")):
                advancing = True
        self.previous = current
        if advancing:
            self.last_progress = now
            self.recovery_count = 0
        idle = max(0, now - self.last_progress)
        muted = bool(samples) and all(row.get("muted") or float(row.get("volume", 0)) <= 0 for row in samples)
        status = ("waiting_for_start" if waiting else "audio_muted" if advancing and muted
                  else "clock_progressing" if advancing else "player_unobservable" if not samples
                  else "clock_stalled" if idle >= self.warning_seconds else "observing_player")
        return {"status": status, "progress": advancing,
                "no_progress_seconds": round(idle, 1), "media_count": len(samples),
                "warning": not waiting and (idle >= self.warning_seconds or (advancing and muted))}


async def observe_player(page: Any) -> list[dict]:
    """Read bounded media state, including same-origin and provider frame players."""
    rows = []
    for frame_index, frame in enumerate(list(page.frames)[:6]):
        try:
            values = await asyncio.wait_for(frame.evaluate(r"""() => {
              const roots=[document];
              for(let i=0;i<roots.length && roots.length<12;i++) {
                for(const node of roots[i].querySelectorAll('*')) {
                  if(node.shadowRoot && roots.length<12) roots.push(node.shadowRoot);
                }
              }
              return roots.flatMap(root=>Array.from(root.querySelectorAll('audio,video')))
                .slice(0,15).map((el,index)=>({index, paused:el.paused, ended:el.ended,
                  current_time:Number(el.currentTime || 0), muted:el.muted, volume:el.volume,
                  duration_seconds:Number.isFinite(el.duration) ? el.duration : null,
                  seekable_end:el.seekable.length ? el.seekable.end(el.seekable.length-1) : null,
                  ready_state:el.readyState, network_state:el.networkState,
                  error_code:el.error ? el.error.code : null,
                  _current_source:el.currentSrc || '',
                  // Only a status attached to this player's container counts.
                  // A global archive heading or a replay button is not proof.
                  recording_status:(() => {
                    const container=el.closest('[data-event-status],[data-webcast-status],'
                      + '[data-event-state],[data-webcast-state],[data-player],'
                      + '[class*="player" i],[id*="player" i]');
                    if(!container || container.closest('nav,aside,header,footer')) return null;
                    const state=['data-event-status','data-webcast-status','data-event-state','data-webcast-state']
                      .map(name=>container.getAttribute(name)||'').find(value=>/^(?:ended|replay|on-demand|archived)$/i.test(value));
                    if(state) return state.toLowerCase();
                    const statuses=Array.from(container.querySelectorAll('[role="status"],[role="alert"]'));
                    for(const item of statuses.slice(0,8)) {
                      const rect=item.getBoundingClientRect(), style=getComputedStyle(item);
                      if(!rect.width || !rect.height || style.display==='none' || style.visibility==='hidden') continue;
                      const text=(item.innerText||'').replace(/\s+/g,' ').trim();
                      if(/^(?:(?:this|the)\s+)?(?:webcast|webinar|broadcast|event|conference call)\s+(?:has\s+)?(?:ended|concluded)[.!]?$/i.test(text)) return 'ended';
                      if(/^(?:(?:this|the)\s+)?(?:webcast|webinar|broadcast|event)\s+(?:is\s+)?(?:now\s+)?available\s+(?:on[- ]demand|as a replay)[.!]?$/i.test(text)) return 'replay';
                    }
                    return null;
                  })()}));
            }"""), timeout=.4)
            for row in values:
                # Persist an opaque exact-source fingerprint, never signed URLs.
                from .source_observation import media_source_descriptor
                row.update(media_source_descriptor(row.pop("_current_source", "")))
                row["key"] = f"{frame_index}:{frame.url}:{row['index']}"
                row["frame_index"] = frame_index
                row["frame_url"] = str(frame.url)
                rows.append(row)
        except Exception:
            continue
    return rows


async def recover_verified_player(agent, page: Any) -> int:
    """Retry play/unmute on a verified event without reloads, seeking or navigation."""
    from .navigation import same_event_route
    try:
        if not await asyncio.wait_for(agent._validate_live_target_page(page), timeout=2):
            return 0
    except Exception:
        return 0
    proof = getattr(agent, "live_target_proof", None) or {}
    target = str(proof.get("target_url") or page.url)
    recovered = 0
    for frame in list(page.frames)[:6]:
        # An unrelated advertisement or other-event iframe can be observed,
        # but cannot be activated merely because the parent event is verified.
        if frame is not page.main_frame and not same_event_route(str(frame.url), target):
            continue
        try:
            recovered += int(await asyncio.wait_for(frame.evaluate("""async () => {
              const roots=[document];
              for(let i=0;i<roots.length && roots.length<12;i++) {
                for(const node of roots[i].querySelectorAll('*')) {
                  if(node.shadowRoot && roots.length<12) roots.push(node.shadowRoot);
                }
              }
              let changed=0;
              for(const el of roots.flatMap(root=>Array.from(root.querySelectorAll('audio,video'))).slice(0,15)) {
                if(el.ended || el.readyState < 2) continue;
                if(el.paused || el.muted || el.volume===0) {
                  el.muted=false; el.volume=1; changed++;
                  try { await Promise.race([el.play(), new Promise(resolve=>setTimeout(resolve,250))]); } catch {}
                }
              }
              return changed;
            }"""), timeout=1))
        except Exception:
            continue
    return recovered


async def hold_playback(agent, page: Any) -> None:
    """A live supervisor, not a one-hour sleep, owns the browser lifetime."""
    if not supervised_live(agent):
        if agent.hold_seconds > 0:
            await asyncio.sleep(agent.hold_seconds)
        return
    interval = max(.05, float(os.getenv("WEBCAST_LIVE_END_POLL_SECONDS", "2")))
    sustain = max(.1, float(os.getenv("WEBCAST_LIVE_END_CONFIRM_SECONDS", "10")))
    observed = None
    evidence = None
    loop = asyncio.get_running_loop()
    monitor = PlaybackProgress(loop.time(), warning_seconds=max(10, float(os.getenv("WEBCAST_PLAYER_STALL_WARNING_SECONDS", "45"))))
    heartbeat = max(2, float(os.getenv("WEBCAST_PLAYER_PROGRESS_INTERVAL_SECONDS", "10")))
    last_observation = float("-inf")
    while True:
        if page.is_closed():
            # The shell checks whether a legitimate ffmpeg fallback is still
            # alive before it labels this authoritative source_lost.
            raise RuntimeError("LIVE_SOURCE_LOST current player page closed")
        try:
            current = await current_event_end_evidence(agent, page)
        except Exception:
            current = None
        now = asyncio.get_running_loop().time()
        if now - last_observation >= heartbeat:
            last_observation = now
            samples = await observe_player(page)
            waiting = False
            if not current:
                try:
                    waiting = bool(await asyncio.wait_for(agent._detect_not_live_event(page), timeout=2))
                except Exception:
                    pass
            state = monitor.observe(samples, now, waiting=waiting)
            from .source_observation import record_source_observation
            record_source_observation(agent, str(page.url), samples, waiting=waiting,
                                      event_ended_evidence=current)
            emit_live_event("playback", "player_observation", ticker=agent.ticker,
                            url=str(page.url), media=samples, **state)
            if state["warning"] and not current:
                if (now - monitor.last_recovery >= 60 and monitor.recovery_count < 3):
                    monitor.last_recovery = now
                    monitor.recovery_count += 1
                    recovered = await recover_verified_player(agent, page)
                    from .diagnostics import capture_diagnostics
                    artifact = await capture_diagnostics(agent, getattr(page, "context", page), "playback_stalled")
                    emit_live_event("playback", "recovery_attempt", status=state["status"],
                                    ticker=agent.ticker, changed_media_count=recovered,
                                    recovery_attempt=monitor.recovery_count, artifact_path=artifact,
                                    next_action="observe_clock_and_audio")
        if current:
            if current != evidence:
                observed, evidence = now, current
            elif observed is not None and now - observed >= sustain:
                write_termination("event_ended", verified=True, evidence=current,
                                  url=str(page.url), proof=getattr(agent, "live_target_proof", None))
                emit_live_event("playback", "event_ended", status="event_ended", progress=True,
                                ticker=agent.ticker, url=str(page.url), evidence=current)
                print(f"[{agent.ticker}] LIVE_EVENT_ENDED verified current-event status", flush=True)
                return
        else:
            observed, evidence = None, None
        await asyncio.sleep(interval)


def process_identity(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def watch_sources(browser_pid: int, pcm_pid: int | None, fallback_pids: list[int], *,
                  poll_seconds: float = .5, loss_grace_seconds: float = 2,
                  tail_seconds: float = 1) -> str:
    """Supervise the selected producer, preserving a legitimate media fallback."""
    identities = {pid: process_identity(pid) for pid in [browser_pid, *fallback_pids]}
    path = Path(os.environ["WEBCAST_LIVE_TERMINATION_FILE"])
    missing_since = None
    def alive(pid):
        return identities.get(pid) is not None and process_identity(pid) == identities[pid]
    while True:
        marker = read_current_termination(path)
        if marker and marker.get("reason") == "event_ended" and marker.get("target_identity_verified") is True:
            reason = "event_ended"
            time.sleep(max(0, tail_seconds))
            break
        source_alive = any(alive(pid) for pid in fallback_pids) if fallback_pids else alive(browser_pid)
        if source_alive:
            missing_since = None
        elif missing_since is None:
            missing_since = time.monotonic()
        elif time.monotonic() - missing_since >= loss_grace_seconds:
            # Browser exit cannot overwrite a positive end already persisted.
            marker = read_current_termination(path)
            if marker and marker.get("reason") == "event_ended" and marker.get("target_identity_verified") is True:
                reason = "event_ended"
                time.sleep(max(0, tail_seconds))
            else:
                reason = "source_lost"
                write_termination(reason, evidence="selected browser/media source process exited")
            break
        time.sleep(max(.02, poll_seconds))
    if pcm_pid:
        try:
            os.kill(pcm_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    print(f"LIVE_SOURCE_TERMINATED reason={reason}", flush=True)
    return reason


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch-sources", action="store_true")
    parser.add_argument("--browser-pid", type=int, required=True)
    parser.add_argument("--pcm-pid", type=int)
    parser.add_argument("--fallback-pid", type=int, action="append", default=[])
    args = parser.parse_args(argv)
    watch_sources(args.browser_pid, args.pcm_pid, args.fallback_pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
