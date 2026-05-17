from __future__ import annotations

import os


REQUIRED_ENV = {
    "OPENAI_API_KEY": "OpenAI key required for fast backup routing",
    "GEMINI_API_KEY": "Gemini key required for primary/review routing",
    "OPENAI_MODEL_FAST": "OpenAI fast model must be configured",
    "GEMINI_MODEL_FAST": "Gemini fast model must be configured",
}


def validate_config() -> list[str]:
    issues: list[str] = []
    for key, message in REQUIRED_ENV.items():
        if not (os.getenv(key) or "").strip():
            issues.append(f"Missing {key}: {message}")
    return issues
