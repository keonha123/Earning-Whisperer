from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from ... import database
except ImportError:  # Allows direct script execution from data_pipeline.
    from data_pipeline import database


def record_context_outcome(context_path: Path, outcome: str, error: str | None = None) -> bool:
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
        recipe_id = int(context["recipe_id"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False

    database.record_webcast_recipe_outcome(
        recipe_id,
        success=outcome == "success",
        error=error,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the audio outcome for a learned webcast recipe.")
    parser.add_argument("--context-file", required=True)
    parser.add_argument("--outcome", choices=("success", "failure"), required=True)
    parser.add_argument("--error", default=None)
    args = parser.parse_args(argv)
    return 0 if record_context_outcome(Path(args.context_file), args.outcome, args.error) else 1


if __name__ == "__main__":
    raise SystemExit(main())
