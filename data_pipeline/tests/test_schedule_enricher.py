from datetime import date
import unittest

from data_pipeline.collectors.schedules.enricher import (
    OfficialScheduleEnricher,
    SearchResult,
)


class OfficialScheduleEnricherTest(unittest.TestCase):
    def test_parses_official_eastern_time_and_converts_to_utc(self):
        page_text = (
            "Domino's Second Quarter 2026 Earnings Webcast When: Monday, July 20 "
            "at 8:30 a.m. ET Where: ir.dominos.com"
        )

        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            page_text,
            date(2026, 7, 20),
            "https://ir.dominos.com/node/24651",
            "https://ir.dominos.com/webcast",
            "official_ir_event",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.source_timezone, "America/New_York")
        self.assertEqual(result.scheduled_at_utc.isoformat(), "2026-07-20T12:30:00+00:00")
        self.assertEqual(result.schedule_source, "official_ir_event")

    def test_rejects_time_when_page_date_does_not_match_yahoo_date(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            "Earnings webcast July 21, 2026 at 8:30 a.m. ET",
            date(2026, 7, 20),
            "https://ir.example.com/event",
            None,
            "official_ir_event",
        )

        self.assertIsNone(result)

    def test_parses_abbreviated_month_and_daylight_timezone(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            "Events Jul 20, 2026 8:30 AM EDT Domino's earnings webcast",
            date(2026, 7, 20),
            "https://ir.dominos.com/",
            None,
            "official_ir_search_index",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.scheduled_at_utc.isoformat(), "2026-07-20T12:30:00+00:00")

    def test_parses_time_before_date_with_eastern_time_label(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            "Conference call begins at 8:30 a.m. Eastern Time on July 21, 2026.",
            date(2026, 7, 21),
            "https://investor.example.com/event",
            None,
            "official_ir_event",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.scheduled_at_utc.isoformat(), "2026-07-21T12:30:00+00:00")

    def test_accepts_only_company_related_trusted_wire_results(self):
        enricher = OfficialScheduleEnricher(api_key="test")
        call = {"ticker": "DPZ", "company_name": "Domino's Pizza"}

        self.assertTrue(
            enricher._is_trusted_wire_result(
                call,
                SearchResult(
                    link="https://www.prnewswire.com/news-releases/dominos-announces-earnings.html",
                    title="Domino's Announces Earnings Webcast",
                    snippet="DPZ will host its conference call.",
                ),
            )
        )
        self.assertFalse(
            enricher._is_trusted_wire_result(
                call,
                SearchResult(
                    link="https://www.prnewswire.com/news-releases/another-company.html",
                    title="Another company announces earnings",
                    snippet="No related issuer details here.",
                ),
            )
        )

    def test_recognizes_same_ir_domain_as_official_source(self):
        enricher = OfficialScheduleEnricher(api_key="test")
        call = {"ir_url": "https://investor.example.com/events"}

        self.assertTrue(
            enricher._is_official_result(
                call,
                SearchResult(
                    link="https://investor.example.com/event-details/q2",
                    title="Q2 Earnings",
                    snippet="",
                ),
            )
        )


if __name__ == "__main__":
    unittest.main()
