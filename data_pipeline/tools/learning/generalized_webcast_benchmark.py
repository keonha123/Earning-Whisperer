from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from ... import database
    from ...collectors.streams.webcast_learning import (
        WebcastCandidate,
        choose_heuristic_candidate,
        make_generalized_patterns,
    )
except ImportError:  # Allows running this file directly.
    from data_pipeline import database
    from data_pipeline.collectors.streams.webcast_learning import (
        WebcastCandidate,
        choose_heuristic_candidate,
        make_generalized_patterns,
    )


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_case(record: dict[str, Any]) -> tuple[list[WebcastCandidate], str] | None:
    try:
        evidence = json.loads(record.get("evidence_json") or "{}")
        expected_id = str(evidence["candidate"]["candidate_id"])
        raw_candidates_path = str(evidence["candidates_path"])
        if raw_candidates_path.startswith("/app/"):
            candidates_path = REPO_ROOT / raw_candidates_path.removeprefix("/app/")
        else:
            candidates_path = Path(raw_candidates_path)
        if not candidates_path.is_absolute():
            candidates_path = REPO_ROOT / candidates_path
        payload = json.loads(candidates_path.read_text(encoding="utf-8"))
        candidates: list[WebcastCandidate] = []
        for row in payload.get("candidates", []):
            # Older snapshots stored prompt fields without selectors.
            row = {
                **row,
                "selectors": row.get("selectors") or [f"snapshot:{row['candidate_id']}"],
            }
            candidates.append(WebcastCandidate.from_dict(row))
        if not any(candidate.candidate_id == expected_id for candidate in candidates):
            return None
        return candidates, expected_id
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def run_benchmark(limit: int | None = None, verbose: bool = False) -> dict[str, int]:
    records = database.get_verified_webcast_recipes_for_benchmark()
    if limit is not None:
        records = records[: max(1, limit)]

    cases = baseline_hits = generalized_hits = both_hits = 0
    skipped = 0
    for record in records:
        loaded = _load_case(record)
        if not loaded:
            skipped += 1
            continue
        candidates, expected_id = loaded
        baseline = choose_heuristic_candidate(candidates)
        leave_one_out = [candidate for candidate in records if candidate["id"] != record["id"]]
        generalized_patterns = make_generalized_patterns(leave_one_out)
        generalized = choose_heuristic_candidate(candidates, generalized_patterns)
        baseline_hit = bool(baseline and baseline.candidate_id == expected_id)
        generalized_hit = bool(generalized and generalized.candidate_id == expected_id)
        if verbose and baseline_hit != generalized_hit:
            baseline_text = next(
                (candidate.text for candidate in candidates if baseline and candidate.candidate_id == baseline.candidate_id),
                "",
            )
            generalized_text = next(
                (candidate.text for candidate in candidates if generalized and candidate.candidate_id == generalized.candidate_id),
                "",
            )
            print(
                "[GeneralizedBenchmark] difference "
                f"recipe_id={record['id']} expected={expected_id} "
                f"baseline={baseline.candidate_id if baseline else None} "
                f"generalized={generalized.candidate_id if generalized else None} "
                f"baseline_text={baseline_text!r} generalized_text={generalized_text!r}"
            )
        cases += 1
        baseline_hits += int(baseline_hit)
        generalized_hits += int(generalized_hit)
        both_hits += int(baseline_hit and generalized_hit)

    result = {
        "records": len(records),
        "cases": cases,
        "skipped": skipped,
        "baseline_hits": baseline_hits,
        "generalized_hits": generalized_hits,
        "both_hits": both_hits,
        "generalized_gain": generalized_hits - baseline_hits,
    }
    print(
        "[GeneralizedBenchmark] "
        + " ".join(f"{key}={value}" for key, value in result.items())
    )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline and cross-domain webcast candidate ranking."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_benchmark(args.limit, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
