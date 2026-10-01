from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
import re

from data_pipeline.collectors.streams.webcast_learning import (
    webcast_artifacts_root as _webcast_artifacts_root,
)


def webcast_artifacts_root() -> Path:
    return _webcast_artifacts_root()


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
        if path.is_file():
            groups[_artifact_group_key(path)].append(path)

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


_RUNTIME_ARTIFACT_PREFIX = re.compile(
    r"^(ew-webcast-[^-]+-[a-f0-9]{10})", re.IGNORECASE
)
_ARTIFACT_MARKERS = (
    "-capture-manifest",
    "-media-candidates",
    "-last-target-url",
    "-active-url",
    "-playback-ready",
    "-recipe",
    "-storage",
    "-learning",
    "-failure",
)


def _artifact_group_key(path: Path) -> str:
    """Group all per-probe files, including extensionless handshake files."""
    match = _RUNTIME_ARTIFACT_PREFIX.match(path.name)
    if match:
        return match.group(1).lower()
    name = path.name
    for marker in _ARTIFACT_MARKERS:
        index = name.lower().find(marker)
        if index > 0:
            return name[:index].lower()
    return path.stem.lower()


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
