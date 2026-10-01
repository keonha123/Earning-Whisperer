"""STT delivery: independent of Whisper model loading."""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
import httpx
from data_pipeline.live_telemetry import emit_live_event
from .config import (
    SttConfig,
    _parse_args,
    config_from_args,
)


@dataclass
class ArchiveSpoolReplay:
    """The records safely moved from the local archive spool in one pass."""

    archived_segments: set[tuple[str, int]]
    terminal_markers: set[tuple[str, int]]
    terminal_sessions: set[str]


class TranscriptEmitter:
    def __init__(self, config: SttConfig) -> None:
        self.config = config
        self.sequence = 0
        self.session_started_monotonic = time.monotonic()
        self.last_emit_ms = 0
        self._archive_retry_after = 0.0
        self._archive_schema_ready = False
        self._last_archived_sequence: int | None = None
        self._last_durable_sequence: int | None = None
        self._last_emitted_sequence: int | None = None
        self._session_end_archived = False
        self._outbox_schema_ready = False
        configured_archive_spool = os.getenv(
            "TRANSCRIPT_ARCHIVE_SPOOL_PATH", ""
        ).strip()
        self._archive_spool_path = Path(
            configured_archive_spool
            or Path(__file__).resolve().parents[1]
            / ".runtime"
            / "transcript-archive-spool.jsonl"
        )
        self._outbox_spool_path = Path(
            os.getenv(
                "STT_OUTBOX_SPOOL_PATH",
                "/tmp/earning-whisperer-transcript-outbox.jsonl",
            )
        )

    def _post_json(
        self,
        client: httpx.Client,
        label: str,
        url: str,
        payload: dict,
        headers: dict | None = None,
    ) -> bool:
        try:
            response = client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.http_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                print(f"[{label}] sent status={response.status_code}", flush=True)
                return True
            print(
                f"[{label}] send failed status={response.status_code} body={response.text[:300]}",
                flush=True,
            )
        except httpx.RequestError as exc:
            print(f"[{label}] send error: {exc}", flush=True)
        return False

    def _queue_delivery(self, payload: dict, destination: str) -> None:
        """Write to the DB outbox, falling back to a local durable spool."""
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if not self._outbox_schema_ready:
                database.ensure_transcript_outbox_schema()
                self._outbox_schema_ready = True
            database.enqueue_transcript_delivery(
                payload,
                destination,
                ensure_schema=False,
            )
        except Exception as exc:
            self._outbox_spool_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from .. import database
            except ImportError:
                import database
            safe_error = database.redact_sensitive_text(str(exc)) or "outbox unavailable"
            spool_record = {
                "destination": destination,
                "payload": payload,
                "last_error": safe_error[:500],
            }
            lock_path = self._outbox_spool_path.with_suffix(
                self._outbox_spool_path.suffix + ".lock"
            )
            with lock_path.open("a", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    with self._outbox_spool_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(spool_record, ensure_ascii=True, default=str)
                            + "\n"
                        )
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            print(f"[Transcript Outbox] DB unavailable; spooled locally: {exc}", flush=True)

    def _replay_local_spool(self) -> None:
        """Move locally spooled deliveries back into MySQL when it recovers."""
        if not self._outbox_spool_path.exists():
            return
        try:
            try:
                from .. import database
            except ImportError:
                import database
            lock_path = self._outbox_spool_path.with_suffix(
                self._outbox_spool_path.suffix + ".lock"
            )
            with lock_path.open("a", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    if not self._outbox_spool_path.exists():
                        return
                    remaining: list[str] = []
                    for line in self._outbox_spool_path.read_text(encoding="utf-8").splitlines():
                        try:
                            record = json.loads(line)
                            database.enqueue_transcript_delivery(
                                record["payload"],
                                record["destination"],
                            )
                        except Exception:
                            remaining.append(line)
                    if remaining:
                        temporary = self._outbox_spool_path.with_suffix(
                            self._outbox_spool_path.suffix + ".tmp"
                        )
                        temporary.write_text(
                            "\n".join(remaining) + "\n", encoding="utf-8"
                        )
                        temporary.replace(self._outbox_spool_path)
                    else:
                        self._outbox_spool_path.unlink(missing_ok=True)
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except Exception as exc:
            print(f"[Transcript Outbox] local spool replay deferred: {exc}", flush=True)

    def _flush_outbox(self, client: httpx.Client, limit: int = 20) -> dict[str, int]:
        """Attempt due deliveries; failed rows remain retryable in the outbox."""
        self._replay_local_spool()
        stats = {"attempted": 0, "sent": 0, "failed": 0}
        try:
            try:
                from .. import database
            except ImportError:
                import database
            rows = database.get_pending_transcript_deliveries(limit=limit)
        except Exception as exc:
            print(f"[Transcript Outbox] flush deferred: {exc}", flush=True)
            return stats

        for row in rows:
            stats["attempted"] += 1
            error: str | None = None
            try:
                payload = json.loads(str(row["payload_json"]))
                destination = str(row["destination"])
                if destination == "ai_engine":
                    sent = self._post_json(
                        client,
                        "AI Engine",
                        f"{self.config.ai_engine_url}/api/v1/analyze",
                        payload,
                    )
                elif destination == "backend":
                    if not self.config.internal_secret:
                        sent = False
                        error = "INTERNAL_SECRET missing"
                    else:
                        sent = self._post_json(
                            client,
                            "Backend Transcript",
                            f"{self.config.backend_url}/api/v1/internal/transcript-segment",
                            payload,
                            headers={"X-Internal-Secret": self.config.internal_secret},
                        )
                        error = None
                else:
                    sent = False
                    error = f"unsupported destination: {destination}"
                if sent:
                    database.mark_transcript_delivery_result(row["id"], success=True)
                    stats["sent"] += 1
                else:
                    delay = min(3600, 30 * (2 ** min(int(row.get("attempt_count") or 0), 7)))
                    database.mark_transcript_delivery_result(
                        row["id"],
                        success=False,
                        error=error or "downstream request failed",
                        retry_delay_seconds=delay,
                    )
                    stats["failed"] += 1
            except Exception as exc:
                database.mark_transcript_delivery_result(
                    row["id"],
                    success=False,
                    error=str(exc),
                    retry_delay_seconds=300,
                )
                stats["failed"] += 1
        return stats

    def _build_transcript_payload(
        self,
        analysis_payload: dict,
        start_ms: int,
        end_ms: int,
    ) -> dict:
        return {
            "ticker": analysis_payload["ticker"],
            "call_id": self.config.call_id,
            "sequence": analysis_payload["sequence"],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": analysis_payload["text_chunk"],
            "speaker": None,
            "timestamp": analysis_payload["timestamp"],
            "is_session_end": analysis_payload["is_final"],
        }

    @staticmethod
    def _segment_key(payload: dict) -> tuple[str, int]:
        return str(payload.get("call_id") or "")[:128], int(payload.get("sequence") or 0)

    def _append_archive_spool(self, record: dict) -> bool:
        """Write archive evidence before attempting MySQL, including a terminal marker."""
        try:
            self._archive_spool_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._archive_spool_path.with_suffix(
                self._archive_spool_path.suffix + ".lock"
            )
            serialized = json.dumps(record, ensure_ascii=True, default=str) + "\n"
            with lock_path.open("a", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    with self._archive_spool_path.open("a", encoding="utf-8") as handle:
                        handle.write(serialized)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        self._archive_spool_path.chmod(0o600)
                    except OSError:
                        pass
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            if record.get("kind") == "segment":
                payload = record.get("payload") or {}
                self._last_durable_sequence = int(payload.get("sequence", 0))
                emit_live_event("archive", "segment_fsynced", status="pending_db", progress=True,
                                transcript_call_id=payload.get("call_id"),
                                fsynced_sequence=self._last_durable_sequence,
                                text_characters=len(str(payload.get("text", ""))))
            return True
        except OSError as exc:
            emit_live_event("archive", "spool_write_failed", status="error", error_type=type(exc).__name__)
            print(
                f"[Transcript Archive] local spool unavailable; direct archive only: {exc}",
                flush=True,
            )
            return False

    def _rewrite_archive_spool(self, remaining: list[str]) -> None:
        if remaining:
            temporary = self._archive_spool_path.with_suffix(
                self._archive_spool_path.suffix + ".tmp"
            )
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write("\n".join(remaining) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.replace(self._archive_spool_path)
        else:
            self._archive_spool_path.unlink(missing_ok=True)

    def _ack_archive_snapshot(self, snapshot: list[str], remaining: list[str]) -> None:
        """Remove only committed snapshot records, retaining concurrent appends."""
        lock_path = self._archive_spool_path.with_suffix(self._archive_spool_path.suffix + ".lock")
        with lock_path.open("a", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                if not self._archive_spool_path.exists():
                    return
                current = self._archive_spool_path.read_text(encoding="utf-8").splitlines()
                # A drainer owns a separate replay lock. Only appends may have
                # happened since its snapshot. Be conservative on unexpected
                # replacement: DB writes are idempotent, deleting unknown text
                # is not. A subsequent replay can safely retry the whole file.
                if current[:len(snapshot)] != snapshot:
                    emit_live_event("archive", "spool_snapshot_changed", status="warning")
                    return
                self._rewrite_archive_spool(remaining + current[len(snapshot):])
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _replay_local_archive_spool(self) -> ArchiveSpoolReplay:
        """Drain a bounded snapshot without holding the writers' lock over DB I/O.

        A separate nonblocking replay lock serializes drainers. The original
        spool stays durable until each DB commit is acknowledged. A killed
        drainer therefore leaves replayable evidence, while live writers can
        continue to fsync new speech even during a database outage.
        """
        replay = ArchiveSpoolReplay(set(), set(), set())
        if not self._archive_spool_path.exists():
            return replay
        snapshot: list[str] = []
        remaining: list[str] = []
        try:
            from .. import database
            replay_path = self._archive_spool_path.with_suffix(self._archive_spool_path.suffix + ".replay.lock")
            with replay_path.open("a", encoding="utf-8") as replay_handle:
                try:
                    fcntl.flock(replay_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    # Another consumer/scheduler drains it; never delay this
                    # live STT consumer waiting for that worker's DB connection.
                    return replay
                try:
                    lock_path = self._archive_spool_path.with_suffix(self._archive_spool_path.suffix + ".lock")
                    with lock_path.open("a", encoding="utf-8") as lock_handle:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                        try:
                            if not self._archive_spool_path.exists():
                                return replay
                            snapshot = self._archive_spool_path.read_text(encoding="utf-8").splitlines()
                        finally:
                            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                    remaining = list(snapshot)
                    try:
                        limit = max(1, min(1000, int(os.getenv("TRANSCRIPT_ARCHIVE_REPLAY_LIMIT", "100"))))
                    except ValueError:
                        limit = 100
                    deadline = time.monotonic() + 2.0
                    if not self._archive_schema_ready:
                        database.ensure_transcript_archive_schema()
                        self._archive_schema_ready = True
                    remaining = []
                    for index, line in enumerate(snapshot):
                        if index >= limit or (index > 0 and time.monotonic() >= deadline):
                            remaining.extend(snapshot[index:])
                            emit_live_event("archive", "replay_batch_pending", status="pending_db",
                                            pending_records=len(remaining))
                            break
                        try:
                            record = json.loads(line)
                            kind = str(record.get("kind") or "")
                            if kind == "segment":
                                payload = record.get("payload")
                                if not isinstance(payload, dict):
                                    raise ValueError("archive spool segment payload is invalid")
                                key = self._segment_key(payload)
                                if not key[0]:
                                    raise ValueError("archive spool segment call_id is missing")
                                database.archive_transcript_segment(payload, ensure_schema=False)
                                replay.archived_segments.add(key)
                                if key[0] == str(self.config.call_id or "")[:128]:
                                    emit_live_event("archive", "segment_db_committed", status="saved", progress=True,
                                                    transcript_call_id=key[0], db_committed_sequence=key[1])
                                if bool(payload.get("is_session_end")):
                                    replay.terminal_sessions.add(key[0])
                            elif kind == "session_end":
                                call_id = str(record.get("call_id") or "")[:128]
                                sequence = int(record.get("sequence") or 0)
                                if not call_id:
                                    raise ValueError("archive spool terminal call_id is missing")
                                if not database.mark_transcript_session_end(
                                    call_id, sequence,
                                    termination_reason=str(record.get("termination_reason") or "legacy_terminal_marker")[:64],
                                    success_eligible=bool(record.get("success_eligible")),
                                    target_identity_verified=bool(record.get("target_identity_verified")),
                                    ensure_schema=False,
                                ):
                                    raise RuntimeError("terminal transcript marker was not found")
                                replay.terminal_markers.add((call_id, sequence))
                                replay.terminal_sessions.add(call_id)
                            else:
                                raise ValueError("unknown archive spool record")
                        except (json.JSONDecodeError, TypeError, ValueError) as exc:
                            print(f"[Transcript Archive] invalid local spool record retained: {exc}", flush=True)
                            remaining.append(line)
                        except Exception as exc:
                            # Do not let a terminal marker pass failed speech.
                            remaining.extend(snapshot[index:])
                            emit_live_event("archive", "db_commit_deferred", status="warning",
                                            pending_records=len(remaining), error_type=type(exc).__name__)
                            print(f"[Transcript Archive] local spool replay deferred: {exc}", flush=True)
                            break
                    self._ack_archive_snapshot(snapshot, remaining)
                finally:
                    fcntl.flock(replay_handle.fileno(), fcntl.LOCK_UN)
        except Exception as exc:
            # No acknowledgement on schema/read/lock failure; the original
            # spool is still present. A crash after DB commit is safe to replay.
            emit_live_event("archive", "db_commit_deferred", status="warning", error_type=type(exc).__name__)
            print(f"[Transcript Archive] local spool replay deferred: {exc}", flush=True)
        return replay

    def _archive_segment_direct(self, payload: dict) -> bool:
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if not self._archive_schema_ready:
                database.ensure_transcript_archive_schema()
                self._archive_schema_ready = True
            database.archive_transcript_segment(payload, ensure_schema=False)
            emit_live_event("archive", "segment_db_committed", status="saved", progress=True,
                            transcript_call_id=payload.get("call_id"), db_committed_sequence=payload.get("sequence"))
            return True
        except Exception as exc:
            self._archive_retry_after = time.monotonic() + 30
            emit_live_event("archive", "db_commit_failed", status="error", error_type=type(exc).__name__)
            print(f"[Transcript Archive] unavailable; live delivery continues: {exc}", flush=True)
            return False

    def _archive_segment(self, payload: dict) -> bool:
        """Archive text through a local write-ahead spool before MySQL."""
        if not self.config.archive_transcripts:
            return False
        key = self._segment_key(payload)
        if not self._append_archive_spool({"kind": "segment", "payload": payload}):
            return self._archive_segment_direct(payload)
        if time.monotonic() < self._archive_retry_after:
            return False
        replay = self._replay_local_archive_spool()
        if key in replay.archived_segments:
            return True
        self._archive_retry_after = time.monotonic() + 30
        return False

    def emit_chunk(self, client: httpx.Client, text: str, is_final: bool = False) -> bool:
        clean_text = text.strip()
        if not clean_text:
            return False

        now_ms = int((time.monotonic() - self.session_started_monotonic) * 1000)
        end_ms = max(now_ms, self.last_emit_ms)
        start_ms = self.last_emit_ms

        analysis_payload = {
            "ticker": self.config.ticker,
            "call_id": self.config.call_id,
            "text_chunk": clean_text,
            "sequence": self.sequence,
            "timestamp": int(time.time()),
            "is_final": is_final,
        }

        emit_live_event("archive", "segment_generated", status="pending", progress=False,
                        transcript_call_id=self.config.call_id, generated_sequence=self.sequence,
                        text_characters=len(clean_text), send_to_backend=self.config.send_to_backend,
                        send_to_ai_engine=self.config.send_to_ai_engine)
        print(f"[TRANSCRIPT GENERATED] sequence={self.sequence} characters={len(clean_text)}", flush=True)

        if self.config.send_to_ai_engine:
            self._queue_delivery(analysis_payload, "ai_engine")

        backend_payload = self._build_transcript_payload(analysis_payload, start_ms, end_ms)
        if self.config.send_to_backend:
            if not self.config.internal_secret:
                print("[Backend Transcript] INTERNAL_SECRET missing; skipped", flush=True)
            else:
                self._queue_delivery(backend_payload, "backend")

        if self.config.send_to_ai_engine or self.config.send_to_backend:
            self._flush_outbox(client)

        # A final delivery chunk is not durable proof that ffmpeg and the
        # capture supervisor exited successfully. Only finish_session() may
        # promote an archived row to the terminal session marker.
        archive_payload = {
            **backend_payload,
            "is_session_end": False,
            "session_end_reason": None,
            "session_success_eligible": False,
            "target_identity_verified": False,
        }
        archived = self._archive_segment(archive_payload)
        if archived:
            self._last_archived_sequence = self.sequence

        self._last_emitted_sequence = self.sequence
        self.sequence += 1
        self.last_emit_ms = end_ms
        return archived

    def finish_session(
        self,
        *,
        termination_reason: str,
        success_eligible: bool,
        target_identity_verified: bool,
    ) -> bool:
        """Persist a classified terminal marker on the last real transcript row."""
        if self._session_end_archived:
            return True
        if (
            not self.config.archive_transcripts
            or self._last_emitted_sequence is None
        ):
            return False
        key = (self.config.call_id[:128], self._last_emitted_sequence)
        if not self._append_archive_spool(
            {
                "kind": "session_end",
                "call_id": key[0],
                "sequence": key[1],
                "termination_reason": str(termination_reason or "unknown")[:64],
                "success_eligible": bool(success_eligible),
                "target_identity_verified": bool(target_identity_verified),
            }
        ):
            return self._mark_session_end_direct(
                key,
                termination_reason=termination_reason,
                success_eligible=success_eligible,
                target_identity_verified=target_identity_verified,
            )
        if time.monotonic() < self._archive_retry_after:
            return False
        replay = self._replay_local_archive_spool()
        self._session_end_archived = (
            key in replay.terminal_markers
            or key[0] in replay.terminal_sessions
        )
        if not self._session_end_archived:
            self._archive_retry_after = time.monotonic() + 30
        return self._session_end_archived

    def _mark_session_end_direct(
        self,
        key: tuple[str, int],
        *,
        termination_reason: str,
        success_eligible: bool,
        target_identity_verified: bool,
    ) -> bool:
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if not self._archive_schema_ready:
                database.ensure_transcript_archive_schema()
                self._archive_schema_ready = True
            marked = database.mark_transcript_session_end(
                key[0],
                key[1],
                termination_reason=str(termination_reason or "unknown")[:64],
                success_eligible=bool(success_eligible),
                target_identity_verified=bool(target_identity_verified),
                ensure_schema=False,
            )
            self._session_end_archived = bool(marked)
            return self._session_end_archived
        except Exception as exc:
            self._archive_retry_after = time.monotonic() + 30
            print(f"[Transcript Archive] terminal marker deferred: {exc}", flush=True)
            return False


def retry_transcript_outbox_once(limit: int = 50) -> None:
    """Replay local transcript evidence and retry downstream delivery queues."""
    args = _parse_args([])
    config = config_from_args(args)
    emitter = TranscriptEmitter(config)
    archive_replay = emitter._replay_local_archive_spool()
    recovered_captures = 0
    try:
        try:
            from .. import database
        except ImportError:
            import database
        recovered_captures = database.complete_recovered_call_captures_from_transcripts(
            archive_replay.terminal_sessions,
            limit=max(1, int(limit)),
        )
    except Exception as exc:
        print(
            f"[Transcript Archive] capture completion recovery deferred: {exc}",
            flush=True,
        )
    with httpx.Client() as client:
        stats = emitter._flush_outbox(client, limit=max(1, int(limit)))
    print(
        "[Transcript Outbox] retry "
        f"attempted={stats['attempted']} sent={stats['sent']} failed={stats['failed']} "
        f"archive_segments={len(archive_replay.archived_segments)} "
        f"archive_terminal_sessions={len(archive_replay.terminal_sessions)} "
        f"recovered_captures={recovered_captures}",
        flush=True,
    )
