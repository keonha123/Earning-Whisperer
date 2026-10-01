import unittest
from unittest import mock

from data_pipeline.tools.replay.internal_ir_discovery import (
    InternalIRDiscovery,
    normalize_url,
    parse_args,
    score_internal_link,
)


class InternalIRDiscoveryTest(unittest.TestCase):
    def test_normalize_url_removes_fragment_and_rejects_documents(self):
        self.assertEqual(
            normalize_url("/events/q2#webcast", base_url="https://ir.example.com/"),
            "https://ir.example.com/events/q2",
        )
        self.assertIsNone(
            normalize_url("/events/q2.pdf", base_url="https://ir.example.com/")
        )

    def test_scores_internal_earnings_replay_link(self):
        score = score_internal_link(
            "https://ir.example.com/events/q2-2026-earnings-webcast-replay",
            label="Listen to the Q2 earnings webcast replay",
            context="Quarterly results conference call",
            ir_host="ir.example.com",
            ticker="MSFT",
            call_year=2026,
        )

        self.assertGreaterEqual(score, 200)

    def test_rejects_generic_ir_home_and_site_search(self):
        self.assertLess(
            score_internal_link(
                "https://ir.example.com/investors",
                label="Investor relations",
                context="Events and presentations",
                ir_host="ir.example.com",
                ticker="MSFT",
                call_year=2026,
            ),
            0,
        )
        self.assertLess(
            score_internal_link(
                "https://ir.example.com/search?search=earnings",
                label="Earnings Release",
                ir_host="ir.example.com",
                ticker="MSFT",
                call_year=2026,
            ),
            0,
        )

    def test_crawl_saves_same_site_and_trusted_provider_candidates(self):
        crawler = InternalIRDiscovery(max_depth=2, max_pages=4, candidates_per_call=5)
        pages = {
            "https://ir.example.com/": (
                "https://ir.example.com/",
                """<a href='/events'>Events and Presentations</a>""",
            ),
            "https://ir.example.com/events": (
                "https://ir.example.com/events",
                """<a href='/events/q2-2026-earnings'>Q2 2026 Earnings Webcast</a>
                   <a href='https://event.on24.com/wcc/r/123'>Listen to Webcast Replay</a>""",
            ),
        }

        with mock.patch.object(crawler, "_sitemap_urls", return_value=[]), mock.patch.object(
            crawler, "_fetch", side_effect=lambda url: pages.get(url)
        ):
            candidates = crawler.discover_call(
                {
                    "ticker": "MSFT",
                    "ir_url": "https://ir.example.com/",
                    "call_year": 2026,
                }
            )

        urls = {candidate.target_url for candidate in candidates}
        self.assertIn("https://ir.example.com/events/q2-2026-earnings", urls)
        self.assertIn("https://event.on24.com/wcc/r/123", urls)

    def test_crawl_reads_provider_urls_from_data_attributes_and_onclick(self):
        crawler = InternalIRDiscovery(max_depth=1, max_pages=2, candidates_per_call=5)
        pages = {
            "https://ir.example.com/": (
                "https://ir.example.com/",
                """<button data-webcast-url='https://event.webcasts.com/replay/123'>
                         Listen to Webcast
                     </button>
                     <div onclick=\"window.open('https://event.on24.com/wcc/r/456')\">
                         Earnings Replay
                     </div>""",
            ),
        }

        with mock.patch.object(crawler, "_sitemap_urls", return_value=[]), mock.patch.object(
            crawler, "_fetch", side_effect=lambda url: pages.get(url)
        ):
            candidates = crawler.discover_call(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/"}
            )

        urls = {candidate.target_url for candidate in candidates}
        self.assertIn("https://event.webcasts.com/replay/123", urls)
        self.assertIn("https://event.on24.com/wcc/r/456", urls)

    def test_crawl_reads_provider_urls_from_iframe_and_inline_script(self):
        crawler = InternalIRDiscovery(max_depth=1, max_pages=2, candidates_per_call=5)
        pages = {
            "https://ir.example.com/": (
                "https://ir.example.com/",
                """<iframe src='https://event.webcasts.com/viewer/123'></iframe>
                   <script>
                     window.replayUrl = "https:\\/\\/event.on24.com\\/wcc\\/r\\/456";
                     window.title = "Quarterly earnings webcast replay";
                   </script>""",
            ),
        }

        with mock.patch.object(crawler, "_sitemap_urls", return_value=[]), mock.patch.object(
            crawler, "_fetch", side_effect=lambda url: pages.get(url)
        ):
            candidates = crawler.discover_call(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/"}
            )

        urls = {candidate.target_url for candidate in candidates}
        self.assertIn("https://event.webcasts.com/viewer/123", urls)
        self.assertIn("https://event.on24.com/wcc/r/456", urls)

    def test_static_event_detail_recovers_embedded_provider_link(self):
        crawler = InternalIRDiscovery(max_depth=1, max_pages=2, candidates_per_call=5)
        event_url = "https://investor.example.com/events/event-details/q2-2026"
        with mock.patch.object(
            crawler,
            "_fetch",
            return_value=(
                event_url,
                """<div class='webcast-link'>
                    <a href='https://edge.media-server.com/mmc/p/abc123'>
                        Click Here for Webcast
                    </a>
                </div>""",
            ),
        ):
            candidates = crawler.discover_provider_links_from_page(
                event_url,
                ir_url="https://investor.example.com/news-releases",
                ticker="CCI",
            )

        self.assertEqual(
            [candidate.target_url for candidate in candidates],
            ["https://edge.media-server.com/mmc/p/abc123"],
        )

    def test_parse_args_supports_depth_and_statuses(self):
        args = parse_args(
            ["--depth", "2", "--max-pages", "6", "--discovery-statuses", "error,no_candidate"]
        )

        self.assertEqual(args.depth, 2)
        self.assertEqual(args.max_pages, 6)
        self.assertEqual(args.discovery_statuses, "error,no_candidate")


if __name__ == "__main__":
    unittest.main()
