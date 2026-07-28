import unittest
from datetime import datetime
from unittest import mock

from data_pipeline.tools.replay.replay_discovery import (
    HistoricalReplayDiscovery,
    build_provider_fallback_query,
    build_replay_query,
    replay_search_candidate,
    select_replay_candidates,
)


class HistoricalReplayDiscoveryTest(unittest.TestCase):
    def test_builds_period_specific_replay_query(self):
        query = build_replay_query(
            {
                "ticker": "MSFT",
                "company_name": "Microsoft Corporation",
                "earning_at": datetime(2026, 7, 17),
            }
        )

        self.assertIn('"Microsoft Corporation"', query)
        self.assertIn("MSFT", query)
        self.assertIn("2026", query)
        self.assertIn("replay", query)

    def test_provider_fallback_excludes_company_ir_domain(self):
        query = build_provider_fallback_query(
            {
                "ticker": "MSFT",
                "company_name": "Microsoft Corporation",
                "earning_at": datetime(2026, 7, 17),
                "ir_url": "https://investor.example.com/events",
            }
        )

        self.assertIn("-site:investor.example.com", query)

    def test_provider_fallback_keeps_external_candidate(self):
        call = {"ir_url": "https://investor.example.com/events"}
        candidates = [
            {"target_url": "https://investor.example.com/events/q2", "score": 200},
            {"target_url": "https://event.on24.com/wcc/r/123", "score": 100},
            {"target_url": "https://investor.example.com/events/q1", "score": 90},
        ]

        selected = select_replay_candidates(
            call,
            candidates,
            limit=2,
            prefer_external_provider=True,
        )

        self.assertEqual(selected[0]["target_url"], "https://event.on24.com/wcc/r/123")
        self.assertEqual(len(selected), 2)

    def test_provider_fallback_only_does_not_repeat_primary_search(self):
        call = {
            "ticker": "MSFT",
            "company_name": "Microsoft Corporation",
            "earning_at": datetime(2026, 7, 17),
            "ir_url": "https://investor.example.com/events",
        }
        discovery = HistoricalReplayDiscovery(api_key="configured")

        with mock.patch.object(discovery, "_search", return_value=[]) as search:
            discovery.search_call(call, provider_fallback_only=True)

        search.assert_called_once()
        self.assertIn("-site:investor.example.com", search.call_args.args[0])

    def test_keeps_official_earnings_webcast_result(self):
        candidate = replay_search_candidate(
            {
                "link": "https://investor.example.com/events/q2-earnings-webcast",
                "title": "Q2 2026 Earnings Conference Call Webcast Replay",
                "snippet": "Listen to the quarterly earnings webcast replay.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["source_kind"], "serper_direct")
        self.assertEqual(candidate["provider_domain"], "investor.example.com")

    def test_keeps_known_webcast_provider_result(self):
        candidate = replay_search_candidate(
            {
                "link": "https://event.on24.com/wcc/r/12345/abc",
                "title": "MSFT Q2 2026 Earnings Webcast Replay",
                "snippet": "Quarterly earnings conference call audio replay.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["source_kind"], "serper_direct")

    def test_rejects_unofficial_transcript_result(self):
        candidate = replay_search_candidate(
            {
                "link": "https://seekingalpha.example/transcript/msft-q2",
                "title": "MSFT Q2 earnings call transcript",
                "snippet": "Earnings conference call transcript and replay.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNone(candidate)

    def test_rejects_generic_ir_page_and_wrong_year(self):
        generic = replay_search_candidate(
            {
                "link": "https://investor.example.com/",
                "title": "Example Investor Relations",
                "snippet": "Find earnings webcast replay information.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )
        wrong_year = replay_search_candidate(
            {
                "link": "https://investor.example.com/events/2025-webcast",
                "title": "2025 Earnings Webcast Replay",
                "snippet": "Listen to the quarterly earnings call.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNone(generic)
        self.assertIsNone(wrong_year)

    def test_keeps_webcast_archive_but_rejects_earnings_release(self):
        archive = replay_search_candidate(
            {
                "link": "https://investor.example.com/webcasts",
                "title": "Webcasts & Presentations",
                "snippet": "2026 earnings webcast archive.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )
        release = replay_search_candidate(
            {
                "link": "https://investor.example.com/news/q2-earnings",
                "title": "Example 2026 Earnings Releases",
                "snippet": "Earnings webcast replay information.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertEqual(archive["source_kind"], "serper_archive")
        self.assertIsNone(release)

    def test_keeps_specific_official_earnings_announcement_as_entrypoint(self):
        candidate = replay_search_candidate(
            {
                "link": "https://investor.example.com/news/q2-2026-earnings",
                "title": "Example Reports Second Quarter 2026 Earnings",
                "snippet": "The release includes a link to the earnings webcast.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["source_kind"], "serper_announcement")

    def test_rejects_announcement_indexes_and_release_date_notices(self):
        reports = replay_search_candidate(
            {
                "link": "https://investor.example.com/reports",
                "title": "Financial & Earnings Reports",
                "snippet": "2026 earnings webcast information.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )
        release_date = replay_search_candidate(
            {
                "link": "https://investor.example.com/news/release-date",
                "title": "Example Announces Earnings Release Date for 2026",
                "snippet": "A future webcast will follow the earnings release.",
            },
            ticker="MSFT",
            ir_url="https://investor.example.com/events",
            earning_at=datetime(2026, 7, 17),
        )

        self.assertIsNone(reports)
        self.assertIsNone(release_date)

    def test_discovery_skips_completed_tickers_and_records_new_results(self):
        calls = [
            {
                "call_id": None,
                "ticker": "DONE",
                "company_name": "Done Inc.",
                "earning_at": datetime(2026, 7, 1),
                "ir_url": "https://done.example.com",
            },
            {
                "call_id": None,
                "ticker": "NEW",
                "company_name": "New Inc.",
                "earning_at": datetime(2026, 7, 1),
                "ir_url": "https://new.example.com",
            },
        ]
        candidate = {
            "target_url": "https://new.example.com/q2-webcast",
            "source_kind": "serper_direct",
            "source_title": "Q2 earnings webcast",
            "source_snippet": "Replay",
            "provider_domain": "new.example.com",
            "score": 100,
        }
        discovery = HistoricalReplayDiscovery(api_key="configured")

        with (
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.get_historical_replay_calls",
                return_value=calls,
            ),
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.claim_historical_replay_discovery",
                side_effect=[False, True],
            ),
            mock.patch.object(discovery, "search_call", return_value=[candidate]) as search,
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.save_historical_replay_targets",
                return_value=1,
            ),
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.record_historical_replay_discovery"
            ) as record,
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.get_historical_replay_discovery_summary",
                return_value=[],
            ),
        ):
            searched, found = discovery.discover()

        self.assertEqual((searched, found), (1, 1))
        search.assert_called_once()
        record.assert_called_once_with(
            "NEW",
            status="discovered",
            candidate_count=1,
        )

    def test_seeds_known_ir_entrypoint_without_search(self):
        calls = [
            {
                "call_id": None,
                "ticker": "MSFT",
                "ir_url": "https://investor.microsoft.com/events",
            }
        ]
        discovery = HistoricalReplayDiscovery(api_key="")

        with (
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.get_historical_replay_calls",
                return_value=calls,
            ),
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.get_historical_replay_discovery_tickers",
                return_value={"MSFT"},
            ),
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.save_historical_replay_targets",
                return_value=1,
            ) as save,
            mock.patch(
                "data_pipeline.tools.replay.replay_discovery.database.record_historical_replay_discovery"
            ) as record,
            mock.patch.object(discovery, "_search") as search,
        ):
            searched, seeded = discovery.seed_ir_entrypoints(
                discovery_statuses={"no_candidate"}
            )

        self.assertEqual((searched, seeded), (1, 1))
        self.assertEqual(
            save.call_args.args[1][0]["target_url"],
            "https://investor.microsoft.com/events",
        )
        record.assert_called_once_with(
            "MSFT",
            status="discovered",
            candidate_count=1,
        )
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
