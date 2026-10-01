"""Regression coverage for malformed issuer pages during live-server startup."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

import requests

from data_pipeline.application.schedules import ScheduleService
from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher


class ScheduleDocumentResilienceTest(unittest.TestCase):
    def setUp(self):
        self.enricher = OfficialScheduleEnricher(api_key="test")
        self.url = "https://investor.example.com/event"

    def response(self, content, mime):
        response = requests.Response()
        response.status_code = 200
        response._content = content
        response.headers["Content-Type"] = mime
        response.url = self.url
        return response

    def test_controls_in_html_tails_do_not_abort_call_time_verification(self):
        # Both literal bytes and numeric references survive recovery in some
        # libxml versions and previously broke _schedule_time_text tail edits.
        for noise in (b"\x00\x01\x08\x0b\x0c\x1f", b"&#1;&#8;&#11;&#12;&#31;"):
            with self.subTest(noise=noise):
                content = (
                    b'<html><body><section><h2>Earnings webcast</h2>'
                    + noise
                    + b'<p>September 17, 2026 at 11:00 a.m. ET</p>'
                    b'<a href="https://events.provider.test/current">Listen to webcast</a>'
                    b'</section></body></html>'
                )
                with mock.patch(
                    "data_pipeline.collectors.schedules.enricher.requests.get",
                    return_value=self.response(content, "text/html; charset=utf-8"),
                ), mock.patch.object(self.enricher, "_fetch_event_page_with_browser") as browser:
                    verified = self.enricher._verify_event_page(
                        self.url, date(2026, 9, 17), "official_ir_event"
                    )
                self.assertIsNotNone(verified)
                self.assertEqual(
                    verified.scheduled_at_utc,
                    datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc),
                )
                self.assertEqual(verified.webcast_url, "https://events.provider.test/current")
                browser.assert_not_called()

    def test_recovered_controls_do_not_break_cached_event_discovery(self):
        self.enricher._page_documents[self.url] = (
            '<article><h2>Earnings webcast</h2>&#1;'
            '<p>September 17, 2026</p>'
            '<a href="https://events.provider.test/current" title="Listen&#1; now">'
            'Listen to webcast</a></article>'
        )
        discovery = self.enricher._discover_cached_event(
            {"ticker": "TEST", "ir_url": self.url},
            self.url,
            date(2026, 9, 17),
            "official_ir_page",
        )
        self.assertIsNotNone(discovery)
        self.assertEqual(discovery.webcast_url, "https://events.provider.test/current")
        self.assertEqual(discovery.webcast_date, date(2026, 9, 17))

    def test_pdf_is_not_html_even_if_mime_is_missing_or_incorrect(self):
        payload = b"%PDF-1.7\nstream\n\x00\x01\x08\nendstream\n%%EOF"
        for mime in ("application/pdf", "", "text/html", "application/octet-stream"):
            with self.subTest(mime=mime), mock.patch(
                "data_pipeline.collectors.schedules.enricher.requests.get",
                return_value=self.response(payload, mime),
            ), mock.patch.object(self.enricher, "_fetch_event_page_with_browser_async") as browser:
                result = self.enricher._verify_event_page(
                    self.url, date(2026, 9, 17), "official_ir_event"
                )
            self.assertIsNone(result)
            browser.assert_not_called()
            self.assertNotIn(self.url, self.enricher._page_documents)
            self.assertFalse(self.enricher._page_fetch_succeeded)
            self.assertEqual(self.enricher._issuer_failures[-1].kind, "issuer_non_html_document")

    def test_non_html_payloads_cannot_supply_call_evidence(self):
        for mime, content in (
            ("application/json", b'{"text":"Earnings webcast September 17, 2026 at 11:00 a.m. ET"}'),
            ("image/svg+xml", b'<svg><text>Earnings webcast September 17, 2026 at 11:00 a.m. ET</text></svg>'),
            ("text/plain", b'Earnings webcast September 17, 2026 at 11:00 a.m. ET'),
        ):
            with self.subTest(mime=mime), mock.patch(
                "data_pipeline.collectors.schedules.enricher.requests.get",
                return_value=self.response(content, mime),
            ):
                self.assertEqual(self.enricher._fetch_event_page(self.url), ("", None))

    def test_mislabeled_html_and_declared_non_ascii_encoding_still_work(self):
        content = (
            '<html><head><meta charset="windows-1252"></head><body>'
            '<p>Société earnings webcast September 17, 2026 at 11:00 a.m. ET</p>'
            '</body></html>'
        ).encode("windows-1252")
        for mime in ("text/html", "application/xhtml+xml", "text/plain", "application/octet-stream", ""):
            with self.subTest(mime=mime), mock.patch(
                "data_pipeline.collectors.schedules.enricher.requests.get",
                return_value=self.response(content, mime),
            ):
                page_text, _ = self.enricher._fetch_event_page(self.url)
            self.assertIn("Société", page_text)
            self.assertIn("11:00 a.m. ET", page_text)

    def test_empty_html_is_an_unverified_document(self):
        with mock.patch(
            "data_pipeline.collectors.schedules.enricher.requests.get",
            return_value=self.response(b"", "text/html"),
        ):
            self.assertEqual(self.enricher._fetch_event_page(self.url), ("", None))

    def test_pdf_event_does_not_prevent_fallback_to_valid_issuer_page(self):
        ir_url = "https://investor.example.com/events"
        responses = {
            self.url: self.response(b"%PDF-1.7\n\x01", "application/pdf"),
            ir_url: self.response(
                b'<p>Earnings webcast September 17, 2026 at 11:00 a.m. ET</p>',
                "text/html",
            ),
        }
        with mock.patch(
            "data_pipeline.collectors.schedules.enricher.requests.get",
            side_effect=lambda url, **kwargs: responses[url],
        ), mock.patch(
            "data_pipeline.collectors.schedules.enricher.database.update_verified_schedule_time"
        ) as update, mock.patch.object(self.enricher, "_search_event_results") as search:
            verified = self.enricher.verify_call({
                "id": 7, "ticker": "TEST", "company_name": "Test",
                "earning_at": date(2026, 9, 17), "event_url": self.url, "ir_url": ir_url,
            })
        self.assertIsNotNone(verified)
        self.assertEqual(verified.event_url, ir_url)
        update.assert_called_once()
        search.assert_not_called()


class ScheduleBatchIsolationTest(unittest.TestCase):
    def test_bad_first_issuer_does_not_abort_remaining_issuers(self):
        calls = [{"id": 1, "ticker": "BAD"}, {"id": 2, "ticker": "GOOD"}, {"id": 3, "ticker": "WAIT"}]
        repository = mock.Mock()
        repository.get_calls_missing_verified_time.return_value = calls
        health = mock.Mock()
        enricher = mock.Mock()
        enricher.verify_call.side_effect = [
            ValueError("All strings must be XML compatible"),
            SimpleNamespace(scheduled_at_utc=datetime(2026, 9, 17, 15)),
            None,
        ]
        service = ScheduleService(
            repository, health, schedule_chain=mock.Mock(), enricher_factory=lambda: enricher
        )
        service.enrich_schedule_times(limit=3)
        self.assertEqual(enricher.verify_call.call_args_list, [mock.call(call) for call in calls])
        health.record_event.assert_called_once_with(
            "schedule_enrichment", ticker="BAD", call_id=1,
            status="failed", error_type="ValueError",
        )


if __name__ == "__main__":
    unittest.main()
