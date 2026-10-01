"""Period/report dates cannot become call dates or hide actual live events."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest

from lxml import html

from data_pipeline.collectors.schedules.call_times import parse_call_times
from data_pipeline.collectors.schedules.event_dates import (
    mask_non_event_dates, non_event_date_reason,
)
from data_pipeline.collectors.schedules.event_routes import fiscal_period
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate, candidate_event_date, candidate_identity_mismatch,
    event_date_from_text, event_identity_text, live_candidate_identity_confirmation,
    live_candidate_match_score, live_event_identity_confirmation,
)


DAY = date(2026, 9, 29)
# Exact saved CCL IR candidate scope from the unsuccessful 2026-09-29 run.
CCL_RESULTS_CARD = (
    "Latest Financial Results Q3 2026 Quarter ended Aug 31, 2026 "
    "Earnings Release PDF Earnings Webcast AUDIO Earnings Presentation PDF "
    "10-Q PDF Latest 10-K PDF"
)


def candidate(context):
    return WebcastCandidate.from_dict({
        "candidate_id": "ccl-webcast", "text": "Earnings Webcast", "tag_name": "a",
        "href_path": "/mediaframe/webcast.html", "context_text": context,
    })


class DateLabelSemanticsTest(unittest.TestCase):
    def test_fiscal_period_end_labels_and_date_formats(self):
        for prefix in (
            "Quarter ended ", "Fiscal year ending on ", "period ended: ",
            "three months ended ", "thirteen weeks ended ", "year-end date: ",
            "end of the fiscal year ", "Quarter ended Monday, ",
        ):
            for stamp in ("Aug 31, 2026", "31 August 2026", "August 31", "2026-08-31",
                          "08/31/2026", "8/31/26", "20260831"):
                with self.subTest(prefix=prefix, stamp=stamp):
                    value = prefix + stamp
                    self.assertEqual(non_event_date_reason(value, len(prefix), len(value)),
                                     "financial_period_end")
                    masked = mask_non_event_dates(value)
                    self.assertNotIn(stamp, masked)
                    self.assertEqual(len(value), len(masked))

    def test_period_ended_date_list_does_not_inherit_into_call(self):
        value = ("quarters ended Aug 31, 2026 and May 31, 2026; "
                 "earnings call September 29, 2026")
        masked = mask_non_event_dates(value)
        self.assertNotIn("Aug 31", masked)
        self.assertNotIn("May 31", masked)
        self.assertIn("September 29, 2026", masked)

    def test_publication_expiry_and_financial_as_of(self):
        for label in ("Published on ", "Updated: ", 'datePublished="',
                      "Publication date: ", "Available through ", "Expires on ",
                      "Registration deadline: ", "Balance sheet as of "):
            with self.subTest(label=label):
                value = label + "2026-08-31"
                self.assertIsNotNone(non_event_date_reason(value, len(label), len(value)))
                self.assertNotIn("2026-08-31", mask_non_event_dates(value))

    def test_genuine_event_dates_and_call_ended_are_untouched(self):
        for value in (
            "Earnings call September 29, 2026", "Call ended September 29, 2026",
            "Call rescheduled from September 29, 2026 to September 30, 2026",
            "Third Quarter 2026 Earnings event-date=2026-09-29",
            "Published earnings call on September 29, 2026",
            "Quarter ended Aug 31, 2026. Event startDate=2026-09-29",
        ):
            with self.subTest(value=value):
                self.assertIn("2026-09-29" if "2026-09-29" in value else "September 29, 2026",
                              mask_non_event_dates(value))

    def test_actual_ccl_quarter_end_is_neither_contradiction_nor_confirmation(self):
        choice = candidate(CCL_RESULTS_CARD)
        self.assertIsNone(candidate_identity_mismatch(choice, target_date=DAY))
        self.assertIsNone(live_candidate_identity_confirmation(choice, target_date=DAY))
        self.assertIsNone(candidate_event_date(choice, live_identity=True))
        self.assertIsNone(live_event_identity_confirmation(CCL_RESULTS_CARD, target_date=DAY))
        # Replay ranking and raw fiscal evidence retain their existing meaning.
        self.assertEqual(candidate_event_date(choice), date(2026, 8, 31))
        self.assertEqual(fiscal_period(CCL_RESULTS_CARD), fiscal_period(event_identity_text(CCL_RESULTS_CARD)))
        self.assertIn("Q3 2026", event_identity_text(CCL_RESULTS_CARD))
        self.assertEqual(live_candidate_match_score(choice, target_date=DAY),
                         live_candidate_match_score(candidate(CCL_RESULTS_CARD.replace("Aug 31, 2026", "")), target_date=DAY))

    def test_saved_ccl_ir_results_scope_does_not_supply_event_date(self):
        fixture = Path(__file__).parent / "fixtures/schedules/ccl-ir-20260930.html"
        document = html.fromstring(fixture.read_text())
        scope = document.xpath('//*[contains(@class, "financial-report-summary__latest-content")]')[0]
        evidence = " ".join(scope.text_content().split())
        self.assertIn("Quarter ended Aug 31, 2026", evidence)
        self.assertIn("Earnings Webcast", evidence)
        self.assertIsNone(candidate_event_date(candidate(evidence), live_identity=True))
        self.assertIsNone(candidate_identity_mismatch(candidate(evidence), target_date=DAY))
        self.assertIsNone(live_event_identity_confirmation(evidence, target_date=DAY))

    def test_real_event_date_wins_only_after_non_event_date_is_removed(self):
        for value in (
            "Quarter ended Aug 31, 2026. Earnings call September 29, 2026",
            "Earnings call September 29, 2026 for the quarter ended Aug 31, 2026",
            "Quarter ended Aug 31, 2026 and earnings call September 29, 2026",
            "Published on October 1, 2026. Earnings call September 29, 2026",
            "Earnings call September 29, 2026; available until December 31, 2026",
        ):
            with self.subTest(value=value):
                self.assertEqual(event_date_from_text(event_identity_text(value)), DAY)
                self.assertIsNone(candidate_identity_mismatch(candidate(value), target_date=DAY))
                self.assertIsNotNone(live_event_identity_confirmation(value, target_date=DAY))

    def test_only_fiscal_end_equal_to_target_cannot_confirm(self):
        value = "Q3 2026 Earnings Webcast quarter ended September 29, 2026"
        self.assertIsNone(live_event_identity_confirmation(value, target_date=DAY))
        self.assertIsNone(live_candidate_identity_confirmation(candidate(value), target_date=DAY))

    def test_actual_other_date_other_fiscal_period_remain_rejected(self):
        value = "Q3 2026 earnings call June 29, 2026; quarter ended August 31, 2026"
        self.assertIn("candidate date 2026-06-29", candidate_identity_mismatch(candidate(value), target_date=DAY))
        self.assertIsNone(live_event_identity_confirmation(value, target_date=DAY))
        self.assertIn("year or quarter", candidate_identity_mismatch(
            candidate(CCL_RESULTS_CARD), target_date=DAY, target_year=2026, target_quarter="Q4"))

    def test_ambiguous_rescheduled_dates_are_not_silently_removed(self):
        value = "Earnings call moved from September 29, 2026 to September 30, 2026"
        self.assertEqual(mask_non_event_dates(value), value)
        self.assertIsNone(live_event_identity_confirmation(value, target_date=DAY))


class CallClockSemanticsTest(unittest.TestCase):
    def test_mixed_quarter_end_and_call_dates_work_in_both_orders(self):
        for value in (
            "Q3 2026 earnings call for the quarter ended Aug 31, 2026 will be held September 29, 2026 at 10 AM ET",
            "Q3 2026 earnings call September 29, 2026 at 10 AM ET for the quarter ended Aug 31, 2026",
            "Q3 2026 quarter ended Aug 31, 2026; earnings call September 29, 2026 at 10 AM ET",
            "Q3 2026 quarter ended 2026-08-31; earnings call 2026-09-29T10:00:00-04:00",
        ):
            with self.subTest(value=value):
                result = parse_call_times(value, DAY, grace_days=0)
                self.assertEqual(result.status, "verified", result)
                self.assertEqual(result.selected.scheduled_at_utc,
                                 datetime(2026, 9, 29, 14, tzinfo=timezone.utc))

    def test_period_date_alone_does_not_supply_clock_date(self):
        for value in (
            "Earnings webcast for quarter ended September 29, 2026 at 10 AM ET",
            "Earnings webcast for quarter ended 2026-09-29T10:00:00-04:00",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_call_times(value, DAY).selected)

    def test_structured_event_start_and_reschedule_are_kept(self):
        value = json.dumps({"@type": "Event", "name": "Q3 2026 Earnings Call",
                            "startDate": "2026-09-30T10:00:00-04:00",
                            "datePublished": "2026-09-20T10:00:00-04:00",
                            "description": "Results for the quarter ended Aug 31, 2026"})
        result = parse_call_times(value, DAY, allow_date_shift=True,
                                  expected_fiscal_year=2026, expected_fiscal_quarter="Q3")
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.selected.webcast_date, date(2026, 9, 30))

    def test_real_clock_conflict_is_kept(self):
        value = ("Earnings call September 29, 2026 at 10 AM ET; "
                 "earnings call September 29, 2026 at 11 AM ET for quarter ended Aug 31, 2026")
        self.assertEqual(parse_call_times(value, DAY).status, "ambiguous")


if __name__ == "__main__":
    unittest.main()
