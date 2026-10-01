from datetime import date, datetime
import unittest
from unittest import mock

import requests

from data_pipeline.collectors.schedules.enricher import (
    EnrichmentFailure,
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

    def test_accepts_nearby_official_call_date_separately_from_release_date(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            "Earnings webcast July 21, 2026 at 8:30 a.m. ET",
            date(2026, 7, 20),
            "https://ir.example.com/event",
            None,
            "official_ir_event",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.webcast_date, date(2026, 7, 21))

    def test_rejects_materially_different_official_call_date(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            "Earnings webcast July 25, 2026 at 8:30 a.m. ET",
            date(2026, 7, 20),
            "https://ir.example.com/event",
            None,
            "official_ir_event",
        )

        self.assertIsNone(result)

    def test_discovers_dated_event_detail_and_provider_url_from_official_dom(self):
        enricher = OfficialScheduleEnricher(api_key="")
        page_url = "https://investor.example.com/events"
        enricher._page_documents[page_url] = """
            <article>
              <h2>Q2 2026 Earnings Call</h2>
              <time>September 10, 2026</time>
              <a href="/events/q2-2026">Event details</a>
              <a data-webcast-url="https://events.provider.test/attendee/42">Listen to webcast</a>
            </article>
        """

        discovery = enricher._discover_cached_event(
            {
                "ticker": "TEST",
                "ir_url": page_url,
            },
            page_url,
            date(2026, 9, 10),
            "official_ir_page",
        )

        self.assertIsNotNone(discovery)
        self.assertEqual(discovery.webcast_date, date(2026, 9, 10))
        self.assertEqual(
            discovery.event_url,
            "https://investor.example.com/events/q2-2026",
        )
        self.assertEqual(
            discovery.webcast_url,
            "https://events.provider.test/attendee/42",
        )
        self.assertIn(
            "target-linked:webcast_url=2026-09-10",
            discovery.evidence,
        )

    def test_does_not_mark_undated_old_webcast_as_target_linked(self):
        enricher = OfficialScheduleEnricher(api_key="")
        page_url = "https://investor.example.com/events"
        enricher._page_documents[page_url] = """
            <article><h2>Q3 earnings date</h2><time>September 10, 2026</time></article>
            <article>
              <h2>Prior Conference Call</h2>
              <a href="https://events.provider.test/attendee/old">Webcast</a>
            </article>
        """

        discovery = enricher._discover_cached_event(
            {"ticker": "TEST", "ir_url": page_url},
            page_url,
            date(2026, 9, 10),
            "official_ir_page",
        )

        self.assertIsNotNone(discovery)
        self.assertNotIn("target-linked:webcast_url=", discovery.evidence)

    def test_parses_json_ld_offset_time(self):
        result = OfficialScheduleEnricher(api_key="test")._parse_verified_time(
            '{"name":"Q2 earnings call","startDate":"2026-09-11T08:00:00-04:00"}',
            date(2026, 9, 10),
            "https://investor.example.com/event",
            None,
            "official_ir_event",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.webcast_date, date(2026, 9, 11))
        self.assertEqual(result.scheduled_at_utc.isoformat(), "2026-09-11T12:00:00+00:00")

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

    def test_reuses_stored_official_event_url_before_searching(self):
        enricher = OfficialScheduleEnricher(api_key="")
        call = {
            "id": 4,
            "ticker": "DPZ",
            "company_name": "Domino's Pizza",
            "earning_at": datetime(2026, 7, 20),
            "ir_url": "https://ir.dominos.com/events",
            "event_url": "https://ir.dominos.com/events/q2-2026",
        }
        verified = enricher._parse_verified_time(
            "Domino's earnings webcast July 20, 2026 at 8:30 a.m. ET",
            date(2026, 7, 20),
            call["event_url"],
            "https://ir.dominos.com/webcast",
            "official_ir_stored_event_http",
        )
        self.assertIsNotNone(verified)

        with (
            mock.patch.object(enricher, "_verify_event_page", return_value=verified) as verify_page,
            mock.patch.object(enricher, "_search_event_results") as search,
            mock.patch("data_pipeline.collectors.schedules.enricher.database.update_verified_schedule_time") as update,
        ):
            result = enricher.verify_call(call)

        self.assertEqual(result, verified)
        verify_page.assert_has_calls([
            mock.call(call["event_url"], date(2026, 7, 20), "official_ir_stored_event"),
            mock.call(call["ir_url"], date(2026, 7, 20), "official_ir_page"),
        ])
        search.assert_not_called()
        update.assert_called_once()

    def test_revalidation_accepts_official_earnings_date_when_time_is_not_published(self):
        enricher = OfficialScheduleEnricher(api_key="")
        call = {
            "id": 9,
            "ticker": "VEEV",
            "company_name": "Veeva Systems",
            "earning_at": datetime(2026, 8, 26),
            "ir_url": "https://ir.veeva.example/events",
            "event_url": "https://ir.veeva.example/events/q2",
            "schedule_revalidation_status": "required",
        }
        date_evidence = (
            "Veeva will release second-quarter financial results on August 26, 2026."
        )

        with (
            mock.patch.object(enricher, "_verify_event_page", return_value=None),
            mock.patch.object(
                enricher,
                "_verify_event_page_date",
                return_value=date_evidence,
            ) as verify_date,
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.confirm_schedule_revalidation_from_official_ir"
            ) as confirm,
            mock.patch.object(enricher, "_search_event_results") as search,
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.record_schedule_enrichment_outcome"
            ) as record_outcome,
        ):
            result = enricher.verify_call(call)

        self.assertIsNone(result)
        verify_date.assert_has_calls([
            mock.call(call["event_url"], date(2026, 8, 26), "official_ir_stored_event"),
            mock.call(call["ir_url"], date(2026, 8, 26), "official_ir_page"),
        ])
        confirm.assert_called_once_with(
            9,
            event_url=call["event_url"],
            evidence=f"official_ir_stored_event: {date_evidence}",
            expected_revision=None, observed_at=mock.ANY,
        )
        record_outcome.assert_called_once()
        search.assert_not_called()

    def test_serper_credit_error_opens_circuit_and_skips_second_query(self):
        enricher = OfficialScheduleEnricher(api_key="test")
        call = {
            "ticker": "DPZ",
            "company_name": "Domino's Pizza",
            "ir_url": "https://ir.dominos.example/events",
        }
        response = mock.Mock(ok=False, status_code=400, text="Not enough credits")

        with (
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.get_schedule_enrichment_circuit",
                return_value=None,
            ),
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.open_schedule_enrichment_circuit"
            ) as open_circuit,
            mock.patch("data_pipeline.collectors.schedules.enricher.requests.post", return_value=response) as post,
        ):
            results = enricher._search_event_results(call, date(2026, 7, 20))

        self.assertEqual(results, [])
        self.assertEqual(post.call_count, 1)
        open_circuit.assert_called_once()
        self.assertEqual(open_circuit.call_args.kwargs["failure_kind"], "serper_credits_exhausted")
        self.assertEqual(open_circuit.call_args.kwargs["retry_minutes"], 720)

    def test_open_serper_circuit_skips_network_request(self):
        enricher = OfficialScheduleEnricher(api_key="test")
        call = {
            "ticker": "DPZ",
            "company_name": "Domino's Pizza",
            "ir_url": "https://ir.dominos.example/events",
        }
        circuit = {
            "failure_kind": "serper_credits_exhausted",
            "retry_not_before": datetime(2026, 7, 20, 12, 0),
        }

        with (
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.get_schedule_enrichment_circuit",
                return_value=circuit,
            ),
            mock.patch("data_pipeline.collectors.schedules.enricher.requests.post") as post,
        ):
            results = enricher._search_event_results(call, date(2026, 7, 20))

        self.assertEqual(results, [])
        post.assert_not_called()
        self.assertEqual(enricher._serper_failure.kind, "serper_circuit_serper_credits_exhausted")

    def test_issuer_timeout_is_persisted_as_per_call_cooldown(self):
        enricher = OfficialScheduleEnricher(api_key="")
        call = {"id": 42, "ticker": "DPZ"}

        with (
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.requests.get",
                side_effect=requests.Timeout(),
            ),
            mock.patch(
                "data_pipeline.collectors.schedules.enricher.database.record_schedule_enrichment_outcome"
            ) as record_outcome,
        ):
            self.assertEqual(enricher._fetch_event_page("https://ir.dominos.example/events"), ("", None))
            enricher._record_unverified_outcome(call)

        record_outcome.assert_called_once_with(
            42,
            failure_kind="issuer_http_timeout",
            error="Issuer event page HTTP request timed out",
            retry_minutes=60,
        )

    def test_issuer_failure_is_not_hidden_by_an_open_serper_circuit(self):
        enricher = OfficialScheduleEnricher(api_key="")
        enricher._issuer_failures = [
            EnrichmentFailure(
                kind="issuer_http_timeout",
                message="Issuer event page HTTP request timed out",
                retry_minutes=60,
            )
        ]
        enricher._serper_failure = EnrichmentFailure(
            kind="serper_circuit_serper_request_error",
            message="Serper circuit open",
            retry_minutes=60,
        )

        with mock.patch(
            "data_pipeline.collectors.schedules.enricher.database.record_schedule_enrichment_outcome"
        ) as record_outcome:
            enricher._record_unverified_outcome({"id": 42, "ticker": "DPZ"})

        self.assertEqual(record_outcome.call_args.kwargs["failure_kind"], "issuer_http_timeout")


if __name__ == "__main__":
    unittest.main()
