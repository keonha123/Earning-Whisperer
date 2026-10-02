from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path


def webcast_artifacts_root() -> Path:
    return Path(
        os.getenv(
            "WEBCAST_ARTIFACTS_DIR",
            str(Path(__file__).resolve().parent / ".artifacts" / "webcast"),
        )
    )


def purge_webcast_artifacts(
    retention_days: int = 14,
    *,
    max_groups: int = 2000,
) -> int:
    """Keep recent screenshot/DOM evidence while bounding generated disk usage."""
    root = webcast_artifacts_root()
    if not root.is_dir():
        return 0

    cutoff = time.time() - max(1, int(retention_days)) * 86400
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".json"}:
            groups[path.stem].append(path)

    removed = 0
    group_mtimes: list[tuple[float, str]] = []
    for stem, paths in groups.items():
        latest_mtime = max(path.stat().st_mtime for path in paths)
        if latest_mtime < cutoff:
            removed += _unlink_group(paths)
        else:
            group_mtimes.append((latest_mtime, stem))

    remaining_limit = max(1, int(max_groups))
    if len(group_mtimes) > remaining_limit:
        group_mtimes.sort()
        by_stem = {stem: paths for stem, paths in groups.items()}
        for _, stem in group_mtimes[: len(group_mtimes) - remaining_limit]:
            removed += _unlink_group(by_stem[stem])
    return removed


def _unlink_group(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            # A concurrent browser process may still own the artifact.
            continue
    return removed
