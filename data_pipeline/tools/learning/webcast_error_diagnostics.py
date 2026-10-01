from __future__ import annotations

import argparse
from collections import defaultdict

try:
    from ... import database
    from .webcast_learning_batch import diagnose_probe_error
except ImportError:  # Allows `python data_pipeline/webcast_error_diagnostics.py`.
    from data_pipeline import database
    from data_pipeline.tools.learning.webcast_learning_batch import diagnose_probe_error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize historical webcast probe errors by root cause.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = database.get_historical_replay_error_records(limit=args.limit)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        category = diagnose_probe_error(record.get("last_error"))
        if args.category and category != args.category:
            continue
        grouped[category].append(record)

    print(f"[ErrorDiagnostics] records={sum(len(items) for items in grouped.values())}")
    for category, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        samples = ", ".join(
            f"{item['ticker']}({item.get('provider_domain') or 'unknown'})"
            for item in items[:8]
        )
        print(f"[ErrorDiagnostics] {category}={len(items)} samples={samples}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
