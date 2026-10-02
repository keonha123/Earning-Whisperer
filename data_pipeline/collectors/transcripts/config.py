from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class TranscriptImportSettings:
    ai_engine_url: str
    request_timeout_seconds: float


def get_transcript_settings() -> TranscriptImportSettings:
    if load_dotenv is not None:
        load_dotenv()
    return TranscriptImportSettings(
        ai_engine_url=os.getenv("AI_ENGINE_URL", "http://localhost:8000").rstrip("/"),
        request_timeout_seconds=_float_env("MANUAL_TRANSCRIPT_TIMEOUT_SECONDS", 30.0),
    )


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


__all__ = ["TranscriptImportSettings", "get_transcript_settings"]
