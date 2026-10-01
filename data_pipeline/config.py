"""Shared environment loading for local, Docker, and module entrypoints."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


DATA_PIPELINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DATA_PIPELINE_ROOT.parent


def load_project_env() -> None:
    """Load repository defaults without overriding shell or Docker values."""
    values = {
        **dotenv_values(REPO_ROOT / ".env"),
        **dotenv_values(DATA_PIPELINE_ROOT / ".env"),
    }
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)

