"""Run v9-native proxy/replay/hybrid backtests for EarningWhisperer AI engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root.parent))


_bootstrap()

from ai_engine.services.research_backtest_service import ResearchBacktestService  # noqa: E402


def _build_service(*, use_database_replay: bool) -> ResearchBacktestService:
    if not use_database_replay:
        return ResearchBacktestService()
    from ai_engine.config import get_settings  # noqa: WPS433
    from ai_engine.db.postgres_executor import PsycopgExecutor  # noqa: WPS433
    from ai_engine.repositories.event_store_repository import EventStoreRepository  # noqa: WPS433

    settings = get_settings()
    executor = PsycopgExecutor(
        settings.database_url,
        settings.database_connect_timeout_seconds,
        settings.database_failure_cooldown_seconds,
    )
    repository = EventStoreRepository(executor, settings.db_schema_path)
    return ResearchBacktestService(settings=settings, repository=repository)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EarningWhisperer v9.4 research backtests.")
    parser.add_argument("--tickers", nargs="*", default=[])
    parser.add_argument("--tickers-file", default="")
    parser.add_argument("--period", default="9mo")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--min-history", type=int, default=35)
    parser.add_argument("--universe-profile", default="auto")
    parser.add_argument("--risk-style", default="CONSERVATIVE")
    parser.add_argument("--mode", choices=["proxy", "replay", "hybrid"], default="proxy")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--use-database-replay", action="store_true", help="Use DATABASE_URL-backed persisted closed replay samples for replay/hybrid mode.")
    parser.add_argument("--acceptance-matrix", action="store_true")
    parser.add_argument("--nasdaq-file", default="data/universes/nasdaq100_20260412.txt")
    parser.add_argument("--sp500-file", default="data/universes/sp500_20260412.txt")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = _build_service(use_database_replay=args.use_database_replay)

    if args.acceptance_matrix:
        nasdaq = service.load_tickers_from_file(args.nasdaq_file)
        sp500 = service.load_tickers_from_file(args.sp500_file)
        payload = service.run_acceptance_matrix(
            nasdaq_tickers=nasdaq,
            sp500_tickers=sp500,
            period=args.period,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
            min_history=args.min_history,
            mode=args.mode,
            output_json=args.output_json or None,
            output_markdown=args.output_md or None,
        )
    else:
        tickers = [ticker.strip().upper() for ticker in args.tickers if ticker and ticker.strip()]
        if args.tickers_file:
            tickers = service.load_tickers_from_file(args.tickers_file)
        if not tickers:
            parser.error("tickers or --tickers-file is required unless --acceptance-matrix is used")
        payload = service.run(
            tickers=tickers,
            period=args.period,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
            min_history=args.min_history,
            universe_profile=args.universe_profile,
            risk_style=args.risk_style,
            mode=args.mode,
            output_json=args.output_json or None,
            output_markdown=args.output_md or None,
        )

    if not args.quiet:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
