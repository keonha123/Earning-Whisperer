"""Private, bounded rescue PCM storage for incomplete live captures.

Active PCM is created on the persistent runtime mount before recording begins.
Cleanup deletes only successfully finished sessions. Failed sessions keep PCM
and a manifest; replay is deliberately manual because whole-consumer sequence
resume has not been implemented. Only the isolated model retries automatically.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, contextmanager
import sys
import fcntl
import shutil
import json
import os
from pathlib import Path
import time
import uuid

from data_pipeline.live_telemetry import emit_live_event


def _integer(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def rescue_root() -> Path:
    return Path(os.getenv("STT_AUDIO_RESCUE_DIR", "") or Path(__file__).resolve().parents[1] / ".runtime" / "audio-rescue")


def _write_private_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_record(path: Path) -> dict:
    if path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def process_identity(pid: int) -> dict:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "process_start": fields[19], "state": fields[0],
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def _alive(identity: dict) -> bool:
    if not identity.get("pid") or not identity.get("process_start"):
        return True  # Incomplete evidence never authorizes reclamation.
    try:
        actual = process_identity(int(identity["pid"]))
        return (actual.get("state") != "Z" and actual["process_start"] == str(identity["process_start"]) and
                (not identity.get("boot_id") or identity["boot_id"] == actual["boot_id"]))
    except (FileNotFoundError, ProcessLookupError):
        return False
    except (OSError, ValueError, IndexError):
        return True


@contextmanager
def _budget_lock(root: Path):
    if root.is_symlink():
        raise OSError("AUDIO_RESCUE_STORAGE_UNAVAILABLE: symlink rescue directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / ".budget.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 3
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("AUDIO_RESCUE_STORAGE_UNAVAILABLE: budget lock busy")
                time.sleep(.02)
        yield
    finally:
        os.close(fd)


def _regular_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() and not path.is_symlink() else 0
    except OSError:
        return 0


def rescue_health_snapshot(root: Path | None = None) -> dict:
    """Read-only; reservations count even before the producer creates its PCM."""
    root = root or rescue_root()
    budget = _integer("STT_AUDIO_RESCUE_TOTAL_MAX_BYTES", 2 * 1024 ** 3)
    reserve = _integer("STT_PCM_HANDOFF_MAX_BYTES", 512 * 1024 ** 2)
    used = sum(_regular_size(p) for p in root.glob("*.pcm"))
    pending = 0
    for record in root.glob("*.reservation.json"):
        pcm = Path(str(record).removesuffix(".reservation.json"))
        metadata = _read_record(record)
        try:
            promised = max(0, int(metadata.get("reserved_bytes", reserve)))
        except (TypeError, ValueError):
            promised = reserve
        pending += max(0, promised - _regular_size(pcm))
    disk_root = root
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    disk_free = shutil.disk_usage(disk_root).free
    available = max(0, min(budget - used - pending, disk_free - pending))
    return {"disk_free_bytes": disk_free, "used_bytes": used, "reserved_bytes": pending, "budget_bytes": budget,
            "reserve_bytes": reserve, "available_bytes": available,
            "available_for_next_recording": reserve > 0 and available >= reserve,
            "orphan_closed_count": sum(1 for p in root.glob("*.pcm")
                if Path(str(p) + ".done").is_file()
                and not Path(str(p) + ".manifest.json").exists()
                and not _alive(_read_record(Path(str(p) + ".owner.json")))),
            "quarantine_bytes": sum(_regular_size(p) for p in (root / "quarantine").glob("*/*.pcm"))}


def _has_reader(pcm: Path) -> bool:
    """Protect an already open consumer, including a late drain after producer exit."""
    try:
        target = pcm.stat()
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                for fd in (proc / "fd").iterdir():
                    try:
                        info = fd.stat()
                        if info.st_dev == target.st_dev and info.st_ino == target.st_ino:
                            return True
                    except FileNotFoundError:
                        continue
                # A consumer waiting to open the PCM is protected as well.
                for name in ("cmdline", "environ"):
                    raw = (proc / name).read_bytes()
                    if str(pcm).encode() in raw.split(b"\0") or b"STT_PCM_HANDOFF_FILE=" + str(pcm).encode() in raw.split(b"\0"):
                        return True
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                return True
        return False
    except OSError:
        return True


def _legacy_runtime_quiescent() -> bool:
    """Legacy owners lack a supervisor identity. Fail closed when DB is unavailable."""
    try:
        from data_pipeline.storage.connection import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            count = conn.execute(text("""SELECT COUNT(*) FROM calls
                WHERE status = 'running' OR stream_probe_status = 'probing'
                   OR capture_lease_until > UTC_TIMESTAMP()
                   OR stream_probe_lease_until > UTC_TIMESTAMP()""")).scalar_one()
        return count == 0
    except Exception:
        return False


def _quarantine(root: Path, pcm: Path, *, now: float) -> bool:
    """Move abandoned audio on the same filesystem; preserve bytes and provenance."""
    archive = root / "quarantine"
    if archive.is_symlink():
        return False
    archive.mkdir(mode=0o700, exist_ok=True)
    maximum = _integer("STT_AUDIO_RESCUE_QUARANTINE_MAX_BYTES", 8 * 1024 ** 3)
    ttl = _integer("STT_AUDIO_RESCUE_QUARANTINE_RETENTION_SECONDS", 604800)
    records = []
    for marker in archive.glob("*/recovery.json"):
        row = _read_record(marker)
        if marker.parent.is_symlink():
            continue
        try:
            records.append((float(row["quarantined_at"]), marker.parent))
        except (KeyError, ValueError, TypeError):
            continue
    total = sum(_regular_size(p) for p in archive.glob("*/*.pcm"))
    size = _regular_size(pcm)
    for closed, directory in sorted(records):
        if now - closed <= ttl:
            continue
        released = sum(_regular_size(p) for p in directory.glob("*.pcm"))
        shutil.rmtree(directory)
        total -= released
        emit_live_event("audio_storage", "quarantine_expired", status="retention", pcm_bytes=released)
    # Never erase recent recovery evidence merely to make room for another file.
    if total + size > maximum:
        return False
    directory = archive / pcm.stem
    directory.mkdir(mode=0o700, exist_ok=True)
    if (directory / pcm.name).exists():
        return False
    _write_private_json(directory / "recovery.json", {
        "version": 1, "quarantined_at": now, "pcm_name": pcm.name,
        "pcm_bytes": size, "reason": "closed_owner_missing", "automatic_consumer_resume": False,
        "owner": _read_record(Path(str(pcm) + ".owner.json")),
        "reservation": _read_record(Path(str(pcm) + ".reservation.json")),
    })
    # PCM moves first; a partial metadata move cannot lose the audio.
    for suffix in ("", ".owner.json", ".done", ".state.json", ".manifest.json", ".reservation.json"):
        source = Path(str(pcm) + suffix)
        if source.exists() and not source.is_symlink():
            os.replace(source, directory / source.name)
    emit_live_event("audio_storage", "orphan_audio_quarantined", status="recovery_required",
                    pcm_bytes=size, recovery_path=str(directory))
    return True


def _prune_locked(root: Path, *, now: float, reserve_bytes: int) -> None:
    ttl = _integer("STT_AUDIO_RESCUE_RETENTION_SECONDS", 172800)
    legacy_quiet = None
    for reservation in root.glob("*.reservation.json"):
        pcm = Path(str(reservation).removesuffix(".reservation.json"))
        metadata = _read_record(reservation)
        if not _alive(metadata.get("supervisor", {})):
            if not pcm.exists():
                reservation.unlink(missing_ok=True)
            elif (not Path(str(pcm) + ".owner.json").exists() and
                  not pcm.is_symlink() and not _has_reader(pcm)):
                _quarantine(root, pcm, now=now)
    for owner in root.glob("*.owner.json"):
        pcm = Path(str(owner).removesuffix(".owner.json"))
        metadata = _read_record(owner)
        if not pcm.is_file() or pcm.is_symlink() or metadata.get("pcm_name") != pcm.name or _alive(metadata):
            continue
        reservation = _read_record(Path(str(pcm) + ".reservation.json"))
        if reservation and _alive(reservation.get("supervisor", {})):
            continue
        try:
            closed = bool(_read_record(Path(str(pcm) + ".done")))
            expired = now - float(metadata["created_at"]) > ttl
        except (KeyError, TypeError, ValueError):
            continue
        # A supervisor reservation proves the whole capture has ended even
        # when SIGKILL prevented the producer from writing its .done marker.
        if not (closed or expired or reservation) or Path(str(pcm) + ".manifest.json").exists() or _has_reader(pcm):
            continue
        if not reservation:
            if legacy_quiet is None:
                legacy_quiet = _legacy_runtime_quiescent()
            if not legacy_quiet:
                continue
        _quarantine(root, pcm, now=now)
    candidates = []
    for manifest in root.glob("*.manifest.json"):
        pcm = Path(str(manifest).removesuffix(".manifest.json"))
        row = _read_record(manifest)
        try:
            if row["pcm_name"] == pcm.name and not pcm.is_symlink():
                candidates.append((float(row["closed_at"]), pcm, manifest))
        except (ValueError, KeyError, TypeError):
            continue
    for closed_at, pcm, manifest in sorted(candidates):
        health = rescue_health_snapshot(root)
        if now - closed_at <= ttl and health["available_bytes"] >= reserve_bytes:
            continue
        reservation = _read_record(Path(str(pcm) + ".reservation.json"))
        owner = _read_record(Path(str(pcm) + ".owner.json"))
        if (reservation and _alive(reservation.get("supervisor", {}))) or (owner and _alive(owner)) or _has_reader(pcm):
            continue
        for suffix in ("", ".done", ".state.json", ".owner.json", ".manifest.json", ".reservation.json"):
            Path(str(pcm) + suffix).unlink(missing_ok=True)
        emit_live_event("audio", "rescue_pruned", status="retention")
    if rescue_health_snapshot(root)["available_bytes"] < reserve_bytes:
        raise OSError("AUDIO_RESCUE_BUDGET_UNAVAILABLE: audio rescue budget unavailable; active recordings are protected")


def prune_rescue(root: Path, *, now: float | None = None, reserve_bytes: int = 0) -> None:
    with _budget_lock(root):
        _prune_locked(root, now=time.time() if now is None else now, reserve_bytes=reserve_bytes)


def allocate_pcm(*, supervisor_pid: int | None = None) -> Path:
    root = rescue_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise OSError("AUDIO_RESCUE_STORAGE_UNAVAILABLE: symlink rescue directory")
    root.chmod(0o700)
    reserve = _integer("STT_PCM_HANDOFF_MAX_BYTES", 512 * 1024 ** 2)
    if reserve <= 0:
        raise OSError("AUDIO_RESCUE_BUDGET_UNAVAILABLE: reservation must be positive")
    supervisor = process_identity(supervisor_pid or os.getpid())
    with _budget_lock(root):
        _prune_locked(root, now=time.time(), reserve_bytes=reserve)
        path = root / (uuid.uuid4().hex + ".pcm")
        _write_private_json(Path(str(path) + ".reservation.json"), {
            "pcm_name": path.name, "reserved_bytes": reserve, "created_at": time.time(),
            "supervisor": supervisor, "call_id": os.getenv("WEBCAST_CALL_DB_ID", ""),
            "capture_session_id": os.getenv("STT_CAPTURE_SESSION_ID", ""),
            "attempt_id": os.getenv("WEBCAST_ATTEMPT_ID", ""),
        })
    return path


def finalize_pcm(path: Path, exit_code: int) -> Path | None:
    with _budget_lock(path.parent):
        result = _finalize_locked(path, exit_code)
        Path(str(path) + ".reservation.json").unlink(missing_ok=True)
        return result


def _finalize_locked(path: Path, exit_code: int) -> Path | None:
    if not path.is_file() or path.is_symlink():
        return None
    if exit_code == 0:
        for artifact in (path, Path(str(path) + ".done"), Path(str(path) + ".state.json"), Path(str(path) + ".owner.json")):
            artifact.unlink(missing_ok=True)
        emit_live_event("audio", "rescue_released", status="completed")
        return None
    path.chmod(0o600)
    state = {}
    try:
        state = json.loads(Path(str(path) + ".state.json").read_text())
    except (OSError, ValueError):
        pass
    manifest = Path(str(path) + ".manifest.json")
    _write_private_json(manifest, {
        "version": 1, "closed_at": time.time(), "exit_code": exit_code,
        "pcm_name": path.name, "pcm_bytes": path.stat().st_size,
        "sample_rate": 16000, "channels": 1, "sample_format": "s16le",
        "call_id": os.getenv("WEBCAST_CALL_DB_ID", ""),
        "ticker": os.getenv("TICKER", ""),
        "capture_session_id": os.getenv("STT_CAPTURE_SESSION_ID", ""),
        "schedule_revision": os.getenv("WEBCAST_SCHEDULE_REVISION", ""),
        "attempt_id": os.getenv("WEBCAST_ATTEMPT_ID", ""),
        "consumer_state": state, "automatic_consumer_resume": False,
        "recovery_note": "Model retries preserve parent sequence; whole-consumer replay requires archive reconciliation.",
    })
    emit_live_event("audio", "rescue_retained", status="recovery_required", progress=True,
                    pcm_bytes=path.stat().st_size, manifest_path=str(manifest),
                    automatic_consumer_resume=False)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allocate", action="store_true")
    parser.add_argument("--finalize")
    parser.add_argument("--supervisor-pid", type=int)
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--exit-code", type=int, default=1)
    args = parser.parse_args(argv)
    if args.allocate:
        try:
            with redirect_stdout(sys.stderr):
                path = allocate_pcm(supervisor_pid=args.supervisor_pid or os.getppid())
        except OSError as exc:
            code = "AUDIO_RESCUE_BUDGET_UNAVAILABLE" if "budget unavailable" in str(exc) or "BUDGET_UNAVAILABLE" in str(exc) else "AUDIO_RESCUE_STORAGE_UNAVAILABLE"
            with redirect_stdout(sys.stderr):
                emit_live_event("audio_storage", "allocation_failed", status="failed", error_code=code,
                                reason="resource_capacity", next_action="reclaim_closed_audio",
                                **rescue_health_snapshot())
            print(f"{code}: {exc}", file=sys.stderr)
            return 73
        print(path)
        return 0
    if args.finalize:
        finalize_pcm(Path(args.finalize), args.exit_code)
        return 0
    if args.reconcile:
        prune_rescue(rescue_root())
    if args.health or args.reconcile:
        print(json.dumps(rescue_health_snapshot(), sort_keys=True))
        return 0
    parser.error("choose --allocate, --finalize, --reconcile or --health")


if __name__ == "__main__":
    raise SystemExit(main())
