import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from data_pipeline.collectors.streams.recipe_outcome import record_context_outcome
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate,
    WebcastRecipe,
    candidate_event_date,
    choose_heuristic_candidate,
    choose_replay_training_candidate,
    choose_replay_training_surface_candidate,
    event_date_from_text,
    extract_response_text,
    future_event_start_utc,
    generalized_candidate_bonus,
    is_dated_earnings_news_article,
    is_replay_training_candidate,
    live_candidate_match_score,
    make_generalized_patterns,
    make_recipe,
    parse_vision_selection,
    replay_candidate_rejection_reason,
    is_non_replay_navigation_link,
    is_news_article_without_playback_label,
)


def candidate(**overrides):
    value = {
        "candidate_id": "candidate-1",
        "selectors": ("#webcast", "main > a:nth-of-type(1)"),
        "frame_hostname": None,
        "text": "Listen to the earnings webcast",
        "aria_label": "",
        "title": "",
        "href_path": "/events/q2-webcast",
        "tag_name": "a",
        "rect": {"x": 10, "y": 20, "width": 120, "height": 32},
        "in_navigation": False,
    }
    value.update(overrides)
    return WebcastCandidate(**value)


class WebcastLearningTest(unittest.TestCase):
    def test_heuristic_prefers_earnings_webcast_over_navigation(self):
        navigation = candidate(
            candidate_id="navigation",
            text="Webcast archive",
            in_navigation=True,
        )
        webcast = candidate(candidate_id="webcast", text="Listen live: Q2 earnings webcast")

        self.assertEqual(choose_heuristic_candidate([navigation, webcast]), webcast)

    def test_live_heuristic_prefers_matching_date_time_and_live_metadata(self):
        old_replay = candidate(
            candidate_id="old-replay",
            text="Listen to Q3 2026 earnings webcast July 30, 2026",
            href_path="/events/q3-2026-replay",
        )
        live_event = candidate(
            candidate_id="live-event",
            text="Join webcast: Q3 2026 earnings call August 27, 2026 2:30 PM ET",
            href_path="/events/q3-2026-live",
            metadata_text="data-status=live datetime=2026-08-27T14:30:00-04:00",
        )

        selected = choose_heuristic_candidate(
            [old_replay, live_event],
            lifecycle="live",
            target_year=2026,
            target_quarter="Q3",
            target_date=date(2026, 8, 27),
            target_time_utc=datetime(2026, 8, 27, 18, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(selected, live_event)

    def test_live_heuristic_prefers_direct_webcast_action_beside_earnings_title(self):
        event_title = candidate(
            candidate_id="frame-0-element-14",
            text="Q3 2026 Earnings Conference Call",
            href_path="/events/event-details/q3-2026-earnings-conference-call",
            context_text="Q3 2026 Earnings Conference Call Sep 9, 2026 5:00 PM ET",
            rect={"x": 0, "y": 596, "width": 360, "height": 24},
            in_navigation=True,
        )
        direct_webcast = candidate(
            candidate_id="frame-0-element-15",
            text="Click here for webcast",
            href_path="/mmc/p/r26d75f6",
            context_text="Click here for webcast",
            rect={"x": 0, "y": 630, "width": 180, "height": 24},
            in_navigation=True,
        )

        selected = choose_heuristic_candidate(
            [event_title, direct_webcast],
            lifecycle="live",
            target_year=2026,
            target_quarter="Q3",
            target_date=date(2026, 9, 9),
        )

        self.assertEqual(selected, direct_webcast)

    def test_future_event_start_observes_the_early_entry_window(self):
        evidence = "Q3 2026 Earnings Call Sep 9, 2026 5:00 PM ET"

        self.assertEqual(
            future_event_start_utc(
                evidence,
                reference_time_utc=datetime(2026, 9, 9, 20, 30, tzinfo=timezone.utc),
                early_entry_minutes=5,
            ),
            datetime(2026, 9, 9, 21, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(
            future_event_start_utc(
                evidence,
                reference_time_utc=datetime(2026, 9, 9, 20, 56, tzinfo=timezone.utc),
                early_entry_minutes=5,
            )
        )

    def test_freshness_metadata_boosts_new_event_without_replacing_event_date(self):
        target_date = date(2026, 8, 27)
        recent = candidate(
            text="Q3 2026 earnings webcast August 27, 2026",
            context_text="Listen to the Q3 2026 earnings webcast August 27, 2026",
            metadata_text="data-status=upcoming data-updated=2026-08-26T18:00:00Z",
        )
        stale = candidate(
            candidate_id="stale",
            text="Q3 2026 earnings webcast August 27, 2026",
            context_text="Listen to the Q3 2026 earnings webcast August 27, 2026",
            metadata_text="data-status=upcoming data-updated=2026-05-01T18:00:00Z",
        )

        self.assertEqual(candidate_event_date(recent), target_date)
        self.assertGreater(
            live_candidate_match_score(recent, target_date=target_date),
            live_candidate_match_score(stale, target_date=target_date),
        )

    def test_heuristic_rejects_calendar_and_footer_links(self):
        calendar = candidate(text="Add event to calendar", href_path="/calendar")
        footer = candidate(
            text="Webcasting Platform Powered by ACCESS Newswire Copyright 2026",
            href_path="/products/investor-relations/earnings-calls",
        )

        self.assertIsNone(choose_heuristic_candidate([calendar, footer]))

    def test_replay_training_rejects_search_navigation(self):
        search = candidate(
            candidate_id="search",
            text="Site Search",
            href_path="/events#site-search",
            context_text="Events Earnings Webcasts Site Search",
        )

        self.assertTrue(is_non_replay_navigation_link(search.href_path, search.text))
        self.assertFalse(is_replay_training_candidate(search))
        self.assertIsNone(choose_replay_training_surface_candidate([search]))

    def test_replay_training_rejects_pdf_viewer_and_event_calendar_index(self):
        pdf = candidate(
            text="PDF, opens in a new window",
            href_path="/tools/viewpdf.aspx?page={event-document}",
        )
        calendar = candidate(
            text="event Event Calendar",
            href_path="/event-calendar",
        )
        self.assertFalse(is_replay_training_candidate(pdf))
        self.assertFalse(is_replay_training_candidate(calendar))

    def test_replay_training_rejects_document_download_without_file_suffix(self):
        document = candidate(
            text="PDF - LINK OPENS IN NEW WINDOW",
            title="First Quarter 2026 Earnings Call Prepared Remarks",
            href_path="/_gallery/get_file/",
            context_text=(
                "4-28-26 First Quarter 2026 Earnings Call Prepared Remarks "
                "PDF - LINK OPENS IN NEW WINDOW"
            ),
        )

        self.assertFalse(is_replay_training_candidate(document))
        self.assertIsNone(choose_replay_training_candidate([document]))

    def test_replay_training_rejects_non_playback_utility_links(self):
        self.assertTrue(
            is_non_replay_navigation_link(
                "/company/media-kit",
                "Advertising Opportunities",
            )
        )

    def test_replay_training_rejects_generic_podcast_hub(self):
        self.assertTrue(
            is_non_replay_navigation_link(
                "https://www.example.com/podcasts/the-morning-filter/episode-5",
                "5 Undervalued Stocks",
            )
        )

    def test_replay_training_rejects_disclaimer_interstitial(self):
        self.assertTrue(
            is_non_replay_navigation_link(
                "https://www.example.com/disclaimer",
                "Disclaimer",
            )
        )

    def test_heuristic_rejects_accessibility_skip_link_on_webcast_article(self):
        skip_link = candidate(
            text="Skip to main content",
            href_path="/news/q2-earnings-webcast",
        )

        self.assertIsNone(choose_heuristic_candidate([skip_link]))

    def test_heuristic_rejects_webcast_slide_documents(self):
        slides = candidate(
            text="Q1 2026 Webcast Slides",
            href_path="/earnings/presentation/webcast-slides.pdf",
        )

        self.assertIsNone(choose_heuristic_candidate([slides]))

    def test_heuristic_rejects_earnings_documents_that_are_not_audio(self):
        documents = [
            candidate(
                text="First Quarter 2026 Investor Presentation",
                href_path="/events/event-details/q1-2026-earnings-conference-call",
            ),
            candidate(
                text="Q2 2026 Earnings Conference Call Prepared Remarks",
                href_path="/events/event-details/q2-2026-earnings-conference-call",
            ),
        ]

        self.assertIsNone(choose_heuristic_candidate(documents))

    def test_replay_training_accepts_non_earnings_webcast_proxy(self):
        proxy = candidate(
            candidate_id="proxy",
            text="Webcast",
            href_path="/events/technology-conference-replay",
            context_text="Technology Conference June 9, 2026 Webcast",
        )
        self.assertTrue(is_replay_training_candidate(proxy))
        self.assertEqual(
            choose_replay_training_candidate([proxy]),
            proxy,
        )

    def test_replay_training_rejects_prepared_remarks_mp3_next_to_webcast(self):
        prepared_remarks = candidate(
            candidate_id="prepared-remarks",
            text="Webcast",
            href_path="/media/document/prepared-remarks.mp3",
            context_text=(
                "Second Quarter 2026 Earnings Prepared Remarks Webcast "
                "Listen to Webcast"
            ),
        )

        self.assertFalse(is_replay_training_candidate(prepared_remarks))
        self.assertIsNone(choose_replay_training_candidate([prepared_remarks]))

    def test_replay_training_accepts_explicit_on_demand_audio_recording(self):
        recording = candidate(
            candidate_id="recording",
            text="Listen to audio recording",
            href_path="/media/earnings-call.mp3",
            context_text="Technology Conference June 9, 2026",
        )

        self.assertTrue(is_replay_training_candidate(recording))
        self.assertEqual(choose_replay_training_candidate([recording]), recording)

    def test_replay_training_accepts_dated_event_with_query_backed_archive_link(self):
        event = candidate(
            candidate_id="axon-event",
            text="Q2 2026 Axon Enterprise Earnings Conference Call",
            href_path="/events-and-presentations",
            selectors=(
                'a[href="https://investor.example.com/events-and-presentations?item=117"]',
            ),
            context_text=(
                "Past Events August 5, 2026 "
                "Q2 2026 Axon Enterprise Earnings Conference Call"
            ),
        )
        self.assertTrue(is_replay_training_candidate(event))
        self.assertEqual(choose_replay_training_candidate([event]), event)

    def test_replay_training_accepts_webinar_proxy(self):
        webinar = candidate(
            candidate_id="webinar",
            text="Customer Panel Webinar",
            href_path="/events/customer-panel",
            context_text="Customer Panel Webinar June 24, 2026 Watch replay",
        )
        self.assertTrue(is_replay_training_candidate(webinar))
        self.assertEqual(choose_replay_training_candidate([webinar]), webinar)

    def test_replay_training_accepts_dated_event_detail_inside_navigation_frame(self):
        event_detail = candidate(
            candidate_id="event-detail",
            text="Second Quarter 2026 Earnings Conference Call",
            href_path="/investors/news-events/ir-calendar/detail/6715/second-quarter-2026-earnings-conference-call",
            context_text="Second Quarter 2026 Earnings Conference Call Aug 6, 2026 10:30 AM ET",
            in_navigation=True,
        )

        self.assertTrue(is_replay_training_candidate(event_detail))
        self.assertEqual(choose_replay_training_candidate([event_detail]), event_detail)

    def test_replay_training_rejects_static_document_proxy(self):
        document = candidate(
            candidate_id="document",
            text="Presentation",
            href_path="/static-files/a206dd85-6572-405b-b78b-acc2367a7ce5",
            context_text="Business Update and Financial Results June 25, 2026",
        )
        self.assertFalse(is_replay_training_candidate(document))
        self.assertIsNone(choose_replay_training_candidate([document]))

    def test_replay_training_rejects_ir_navigation_label(self):
        navigation = candidate(
            text="Events & Presentations",
            href_path="/events-presentations",
            context_text="News & Events Events & Presentations",
        )
        self.assertFalse(is_replay_training_candidate(navigation))
        self.assertIsNone(choose_replay_training_candidate([navigation]))

    def test_replay_training_rejects_social_share_intent(self):
        share = candidate(
            text="",
            href_path="/i/jf/onboarding/web?redirect_after_login=%2Fintent%2Ftweet%3Furl%3Dhttps%253A%252F%252Finvestor.example.com%252Fevents",
        )
        self.assertTrue(is_non_replay_navigation_link(
            "https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fintent%2Ftweet%3Furl%3Dhttps%253A%252F%252Finvestor.example.com%252Fevents"
        ))
        self.assertFalse(is_replay_training_candidate(share))

    def test_replay_training_rejects_upcoming_schedule_surface(self):
        self.assertTrue(is_non_replay_navigation_link(
            "https://investor.example.com/financial-information/upcoming-earnings",
            "Upcoming Earnings",
        ))
        self.assertFalse(is_non_replay_navigation_link(
            "https://investor.example.com/events/q2-2026-webcast",
            "Webcast",
        ))

    def test_replay_training_rejects_company_about_page_even_with_audio_label(self):
        self.assertTrue(is_non_replay_navigation_link(
            "https://www.fcx.com/about",
            "Get an audio challenge",
        ))

    def test_replay_training_rejects_sec_filing_surface(self):
        filing = candidate(
            text="All UnitedHealth Group SEC Filings",
            href_path="https://www.sec.gov/cgi-bin/browse-edgar?company=unitedhealth+group&action=getcompany",
        )
        self.assertTrue(is_non_replay_navigation_link(filing.href_path, filing.text))
        self.assertFalse(is_replay_training_candidate(filing))

    def test_replay_training_rejects_generic_stock_navigation_surface(self):
        stock = candidate(
            text="see here",
            href_path="https://www.unitedhealthgroup.com/investors/stock.html",
        )
        self.assertTrue(is_non_replay_navigation_link(stock.href_path, stock.text))
        self.assertFalse(is_replay_training_candidate(stock))

    def test_replay_training_rejects_company_homepage_link(self):
        homepage = candidate(
            text="Carvana - link to home page",
            href_path="/",
            context_text="Carvana",
        )
        self.assertFalse(is_replay_training_candidate(homepage))
        self.assertIsNone(choose_replay_training_candidate([homepage]))

    def test_replay_training_rejects_player_adjacent_document_controls(self):
        controls = [
            candidate(
                text="Presentation Mode",
                href_path="",
                context_text="Investor Relations presentation viewer",
            ),
            candidate(
                text="Investor Relations Email",
                href_path="/investor-relations/email",
                context_text="Investor Relations Resources",
            ),
        ]

        self.assertIsNone(choose_replay_training_candidate(controls))

    def test_replay_training_rejects_regulatory_news_article_without_playback_label(self):
        article = candidate(
            text="Smurfit-Westrock plc Form 10-Q for the Quarterly Period",
            href_path="/regulatory-news/news-details/2026/form-10-q/default.aspx",
            context_text="Quarterly financial results August 2026",
        )

        self.assertFalse(is_replay_training_candidate(article))
        self.assertIsNone(choose_replay_training_candidate([article]))

    def test_replay_training_rejects_event_title_that_links_back_to_archive(self):
        archive_link = candidate(
            text="Barclays 28th Annual Global Healthcare Conference",
            href_path="/events-presentations",
            context_text="Past Events March 10, 2026 Barclays 28th Annual Global Healthcare Conference",
        )
        self.assertFalse(is_replay_training_candidate(archive_link))

    def test_replay_training_rejects_tentative_event(self):
        tentative = candidate(
            text="Q3 2026 Earnings Conference Call (tentative)",
            href_path="/events/event-details/q3-2026-earnings-call-tentative",
        )

        self.assertEqual(
            replay_candidate_rejection_reason(
                tentative.text,
                tentative.href_path,
                reference_date=date(2026, 8, 18),
            ),
            "event is tentative and cannot train replay playback",
        )
        self.assertFalse(is_replay_training_candidate(tentative))

    def test_replay_training_rejects_authentication_surface(self):
        login = candidate(
            text="Fourth Quarter 2024 Financial Results Login",
            href_path="/login/dollargeneral20250313",
        )

        self.assertFalse(is_replay_training_candidate(login))
        self.assertIsNone(choose_replay_training_candidate([login]))

    def test_replay_training_rejects_presentations_archive_route(self):
        archive = candidate(
            text="View All Presentations",
            href_path="/news-events/presentations",
            context_text="Investor Relations Presentations Webcast Archive",
        )

        self.assertFalse(is_replay_training_candidate(archive))
        self.assertIsNone(choose_replay_training_candidate([archive]))

    def test_replay_rejects_non_news_scheduled_announcement(self):
        announcement = candidate(
            text="Cincinnati Financial Schedules Webcast to Discuss Second Quarter 2026 Results",
            href_path="/2026-07-08-cincinnati-financial-schedules-webcast",
        )

        self.assertEqual(
            replay_candidate_rejection_reason(
                announcement.text,
                announcement.href_path,
                reference_date=date(2026, 8, 18),
            ),
            "event announcement is not a playback surface",
        )
        self.assertFalse(is_replay_training_candidate(announcement))

    def test_replay_training_accepts_dated_earnings_detail_link(self):
        latest = candidate(
            candidate_id="latest",
            text="CENTENE CORPORATION SECOND QUARTER 2026 EARNINGS",
            href_path="/Centene-Corporation-Second-Quarter-2026-Earnings",
            context_text="Tuesday, July 28, 2026 CENTENE CORPORATION SECOND QUARTER 2026 EARNINGS",
        )
        older = candidate(
            candidate_id="older",
            text="CENTENE CORPORATION SECOND QUARTER 2025 EARNINGS",
            href_path="/2Q-2025-Centene-Corporation-Earnings-Conference-Call",
            context_text="Friday, July 25, 2025 CENTENE CORPORATION SECOND QUARTER 2025 EARNINGS",
        )

        self.assertTrue(
            is_replay_training_candidate(
                latest,
                reference_date=date(2026, 8, 13),
            )
        )
        self.assertEqual(
            choose_replay_training_candidate(
                [older, latest],
                reference_date=date(2026, 8, 13),
            ),
            latest,
        )

    def test_replay_surface_fallback_accepts_dated_event_detail_without_webcast_label(self):
        detail = candidate(
            candidate_id="detail",
            text="Second Quarter 2026 Results",
            href_path="/events/2026/second-quarter-results",
            context_text="July 30, 2026 Second Quarter 2026 Results",
        )

        self.assertEqual(
            choose_replay_training_surface_candidate(
                [detail],
                reference_date=date(2026, 8, 18),
            ),
            detail,
        )

    def test_replay_surface_fallback_rejects_future_and_document_links(self):
        future = candidate(
            candidate_id="future",
            text="Q3 2026 Earnings Results",
            href_path="/events/q3-2026-results",
            context_text="September 1, 2026 Q3 2026 Earnings Results",
        )
        document = candidate(
            candidate_id="document",
            text="Q2 2026 Results",
            href_path="/events/q2-2026-results.pdf",
            context_text="July 30, 2026 Q2 2026 Results",
        )

        self.assertIsNone(
            choose_replay_training_surface_candidate(
                [future, document],
                reference_date=date(2026, 8, 18),
            )
        )

    def test_replay_surface_fallback_rejects_governance_navigation_with_pagewide_video_text(self):
        governance = candidate(
            text="Corporate Governance Our Board of Directors and Governance Documents",
            href_path="/corporate-governance/board-of-directors-and-board-diversity-matrix",
            context_text=(
                "Events Investors Videos Upcoming Earnings Release Dates "
                "Corporate Governance Our Board of Directors"
            ),
            in_navigation=False,
        )

        self.assertFalse(is_replay_training_candidate(governance))
        self.assertIsNone(choose_replay_training_surface_candidate([governance]))

    def test_heuristic_rejects_press_release_route_even_when_title_mentions_webcast(self):
        press_release = candidate(
            text="FirstEnergy to Webcast Fourth Quarter Earnings Teleconference",
            href_path="/news-releases/firstenergy-to-webcast-fourth-quarter-earnings-teleconference",
        )

        self.assertIsNone(choose_heuristic_candidate([press_release]))

    def test_heuristic_rejects_subscription_links_as_playback_candidates(self):
        subscribe = candidate(
            text="Subscribe to Earnings Conference Call",
            href_path="/email-alerts",
        )

        self.assertIsNone(choose_heuristic_candidate([subscribe]))

        podcast = candidate(
            text="Listen To Our Podcasts",
            href_path="/insights/podcasts/thoughts-on-the-market",
        )
        self.assertTrue(
            is_non_replay_navigation_link(
                podcast.href_path or "",
                podcast.text,
            )
        )
        self.assertIsNone(choose_replay_training_candidate([podcast]))

        client_story = candidate(
            text="Watch Our Client Success Stories",
            href_path="/what-we-do/blueprint",
        )
        self.assertTrue(
            is_non_replay_navigation_link(
                client_story.href_path or "",
                client_story.text,
            )
        )
        self.assertIsNone(choose_replay_training_candidate([client_story]))

        privacy = candidate(
            text="Privacy Preferences",
            href_path="#cookie-preferences",
        )
        self.assertIsNone(choose_heuristic_candidate([privacy]))

    def test_heuristic_prefers_webcast_over_event_announcement_document(self):
        event_announcement = candidate(
            candidate_id="announcement",
            text="Event Announcement",
            href_path="/news/press-release/pfizer-invites-shareholders-view-and-listen-webcast-april.pdf",
            context_text="Pfizer Quarterly Corporate Performance Q2 2026 Webcast Event Announcement",
        )
        webcast = candidate(
            candidate_id="webcast",
            text="Webcast",
            href_path="/Launch/QReg/ShowUUID=earnings-q1",
            context_text="Pfizer Quarterly Corporate Performance Q1 2026 Webcast",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [event_announcement, webcast],
                lifecycle="replay",
                reference_date=date(2026, 7, 27),
            ),
            webcast,
        )

    def test_replay_accepts_earnings_event_detail_link_without_webcast_label(self):
        event_detail = candidate(
            text="lululemon athletica Q1 2026 Results",
            href_path="/investors/news-and-events/events-and-presentations/2026/lululemon-athletica-q1-2026-results",
        )

        self.assertEqual(
            choose_heuristic_candidate([event_detail], lifecycle="replay"),
            event_detail,
        )

    def test_heuristic_accepts_icon_only_provider_player_link(self):
        player = candidate(
            text="",
            href_path="/mediaframe/webcast.html",
            context_text="07/29/26 Q2 2026 Earnings Conference Call",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [player],
                lifecycle="replay",
                target_year=2026,
                target_quarter="Q2",
            ),
            player,
        )

    def test_heuristic_accepts_contextual_audio_file_link(self):
        audio = candidate(
            text="Q2 2026 Earnings Call Conference",
            href_path="/static-files/call_audio.mp3",
            context_text="Q2 2026 Earnings Call Conference",
        )

        self.assertEqual(choose_heuristic_candidate([audio]), audio)

    def test_heuristic_rejects_bare_media_link_without_earnings_context(self):
        unrelated = candidate(
            text="",
            href_path="/mediaframe/webcast.html",
            context_text="Annual Investor Day Presentation",
        )

        self.assertIsNone(choose_heuristic_candidate([unrelated]))

    def test_replay_lifecycle_prefers_replay_over_registration(self):
        register = candidate(
            candidate_id="register",
            text="Register for Webcast",
            href_path="/mmc/p/upcoming",
        )
        replay = candidate(
            candidate_id="replay",
            text="Webcast Replay",
            href_path="/mmc/p/archive",
            in_navigation=True,
        )

        self.assertEqual(
            choose_heuristic_candidate([register, replay], lifecycle="replay"),
            replay,
        )

    def test_candidate_selection_uses_target_quarter_and_year(self):
        q2 = candidate(
            candidate_id="q2",
            text="Q2 2026 Register for Webcast",
            href_path="/mmc/p/q2",
        )
        q1 = candidate(
            candidate_id="q1",
            text="Q1 2026 Webcast Replay",
            href_path="/mmc/p/q1",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [q2, q1],
                lifecycle="replay",
                target_year=2026,
                target_quarter="Q1",
            ),
            q1,
        )

    def test_replay_ignores_future_event_and_uses_latest_past_event(self):
        upcoming = candidate(
            candidate_id="q2",
            text="Webcast",
            href_path="/attendee/upcoming",
            context_text="Q2 2026 Earnings Call August 6, 2026 Webcast",
        )
        latest_past = candidate(
            candidate_id="q1",
            text="Webcast",
            href_path="/attendee/q1",
            context_text="Q1 2026 Earnings Call May 7, 2026 Webcast",
        )
        older = candidate(
            candidate_id="q4",
            text="Webcast",
            href_path="/attendee/q4",
            context_text="Q4 2025 Earnings Call February 12, 2026 Webcast",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [upcoming, latest_past, older],
                lifecycle="replay",
                reference_date=date(2026, 7, 27),
            ),
            latest_past,
        )

    def test_replay_falls_back_from_future_target_quarter(self):
        upcoming = candidate(
            candidate_id="q2",
            text="Q2 2026 Earnings Webcast",
            context_text="August 4, 2026",
        )
        latest_past = candidate(
            candidate_id="q1",
            text="Q1 2026 Earnings Webcast",
            context_text="April 30, 2026",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [upcoming, latest_past],
                lifecycle="replay",
                target_year=2026,
                target_quarter="Q2",
                reference_date=date(2026, 7, 27),
            ),
            latest_past,
        )

    def test_candidate_event_date_uses_surrounding_event_context(self):
        webcast = candidate(
            text="Webcast",
            context_text="Airbnb Q1 2026 Earnings Call May 07, 2026",
        )

        self.assertEqual(candidate_event_date(webcast), date(2026, 5, 7))

    def test_candidate_event_date_reads_compact_url_and_day_first_date(self):
        compact_url = candidate(
            text="Fourth Quarter Earnings Call",
            href_path="/event-detail/20260806-fourth-quarter-earnings-call",
        )

        self.assertEqual(candidate_event_date(compact_url), date(2026, 8, 6))
        self.assertEqual(
            event_date_from_text("30th July 2026 Q2 Results View Webcast"),
            date(2026, 7, 30),
        )

    def test_replay_skips_too_fresh_event_and_uses_stable_archive(self):
        yesterday = candidate(
            candidate_id="fresh",
            text="View Webcast",
            href_path="/attendee/fresh",
            context_text="30th July 2026 Q2 Results",
        )
        archived = candidate(
            candidate_id="archived",
            text="View Webcast",
            href_path="/attendee/archived",
            context_text="30th April 2026 Q1 Results",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [yesterday, archived],
                lifecycle="replay",
                reference_date=date(2026, 7, 31),
            ),
            archived,
        )

    def test_replay_keeps_direct_provider_link_when_page_has_future_schedule(self):
        provider_link = candidate(
            candidate_id="provider",
            text="Listen to webcast",
            href_path="/mmc/p/replay-token",
            selectors=(
                '[aria-label="Listen to webcast"]',
                'a[href="https://edge.media-server.com/mmc/p/replay-token"]',
            ),
            context_text=(
                "Q1 2026 Earnings Call April 28, 2026. "
                "The next earnings event is scheduled for October 20, 2026."
            ),
        )

        self.assertEqual(
            choose_replay_training_candidate(
                [provider_link],
                reference_date=date(2026, 8, 24),
            ),
            provider_link,
        )

    def test_replay_prefers_quarter_results_over_newer_non_earnings_webcast(self):
        acquisition = candidate(
            candidate_id="acquisition",
            text="View Webcast",
            href_path="/attendee/acquisition",
            context_text=(
                "22nd June 2026 CRH to Acquire Arcosa "
                "View Download View Webcast Presentation"
            ),
        )
        quarter_results = candidate(
            candidate_id="results",
            text="View Webcast",
            href_path="/attendee/q1-results",
            context_text=(
                "30th April 2026 Q1 2026 Results "
                "View Download View Webcast Presentation Form 10-Q"
            ),
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [acquisition, quarter_results],
                lifecycle="replay",
                reference_date=date(2026, 7, 31),
            ),
            quarter_results,
        )

    def test_replay_rejects_news_article_that_only_announces_call(self):
        announcement = candidate(
            text="Walmart To Host First Quarter Earnings Conference Call May 21, 2026",
            href_path=(
                "/news/2026/05/14/"
                "walmart-to-host-first-quarter-earnings-conference-call-may-21-2026"
            ),
        )

        self.assertIsNotNone(
            replay_candidate_rejection_reason(
                announcement.text,
                announcement.href_path,
                reference_date=date(2026, 7, 31),
            )
        )
        self.assertIsNone(
            choose_heuristic_candidate(
                [announcement],
                lifecycle="replay",
                reference_date=date(2026, 7, 31),
            )
        )

    def test_replay_rejects_news_article_recipe_without_playback_label(self):
        self.assertTrue(
            is_news_article_without_playback_label(
                "UnitedHealth Group authorizes payment of quarterly dividend",
                "/newsroom/2026/2026-08-12-uhg-authorizes-payment-quarterly-dividend.html",
            )
        )
        self.assertFalse(
            is_news_article_without_playback_label(
                "UnitedHealth Group Q2 Earnings Webcast",
                "/newsroom/2026/2026-07-16-uhg-reports-second-quarter-2026-results.html",
            )
        )

    def test_replay_allows_old_earnings_release_as_discovery_page(self):
        release = candidate(
            text="Walmart Releases Q1 FY27 Earnings",
            href_path="/news/2026/05/21/walmart-releases-q1-fy27-earnings",
            context_text="Walmart Releases Q1 FY27 Earnings May 21, 2026 | Finance",
        )

        self.assertTrue(
            is_dated_earnings_news_article(
                release,
                reference_date=date(2026, 8, 14),
            )
        )
        self.assertTrue(
            is_replay_training_candidate(
                release,
                reference_date=date(2026, 8, 14),
            )
        )

    def test_replay_keeps_old_host_call_announcement_out(self):
        announcement = candidate(
            text="Walmart To Host First Quarter Earnings Conference Call May 21, 2026",
            href_path="/news/2026/05/14/walmart-to-host-first-quarter-earnings-conference-call-may-21-2026",
            context_text="Walmart To Host First Quarter Earnings Conference Call May 21, 2026",
        )

        self.assertFalse(
            is_dated_earnings_news_article(
                announcement,
                reference_date=date(2026, 8, 14),
            )
        )
        self.assertFalse(
            is_replay_training_candidate(
                announcement,
                reference_date=date(2026, 8, 14),
            )
        )

    def test_replay_rejects_future_year_announcement_without_full_date(self):
        announcement = candidate(
            text="BNY Announces Conference Calls to Review Earnings in 2027",
            href_path="/newsroom/press-release/earnings-in-2027.html",
        )

        self.assertIsNone(
            choose_heuristic_candidate(
                [announcement],
                lifecycle="replay",
                reference_date=date(2026, 8, 6),
            )
        )

    def test_replay_rejects_back_to_top_with_pagewide_earnings_context(self):
        back_to_top = candidate(
            text="Back to Top",
            href_path="/presentations-and-webcasts",
            context_text="Q1 2026 Earnings Conference Call Webcast Replay",
            in_navigation=True,
        )

        self.assertIsNone(
            choose_heuristic_candidate(
                [back_to_top],
                lifecycle="replay",
                reference_date=date(2026, 8, 6),
            )
        )

    def test_replay_reads_future_event_date_from_stable_selector(self):
        upcoming = candidate(
            candidate_id="upcoming",
            text="Q4 Fiscal 2026 Earnings Conference Call Webcast",
            href_path="/registration",
            selectors=("#08-19-2026 a",),
        )
        archived = candidate(
            candidate_id="archived",
            text="Q2 Fiscal 2026 Earnings Conference Call Webcast Replay",
            href_path="/replay/q2",
            context_text="May 1, 2026",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [upcoming, archived],
                lifecycle="replay",
                reference_date=date(2026, 8, 6),
            ),
            archived,
        )

    def test_icon_media_link_can_use_nearby_earnings_href_context(self):
        earnings_document = candidate(
            candidate_id="frame-0-element-1",
            text="arrow_forward",
            href_path="/investor-relations/earnings/q2-2026-results.pdf",
            rect={"x": 0, "y": 100, "width": 20, "height": 20},
        )
        player = candidate(
            candidate_id="frame-0-element-2",
            text="launch",
            href_path="/mediaframe/webcast.html",
            context_text="",
            rect={"x": 0, "y": 125, "width": 20, "height": 20},
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [earnings_document, player],
                lifecycle="replay",
                reference_date=date(2026, 8, 6),
            ),
            player,
        )

    def test_read_more_news_card_does_not_beat_webcast(self):
        news_card = candidate(
            candidate_id="news",
            text=(
                "Veralto Schedules Second Quarter 2026 Earnings Call and will "
                "webcast its results Read More"
            ),
            href_path="/2026-07-28-Veralto-Reports-Second-Quarter-2026-Results",
        )
        webcast = candidate(
            candidate_id="webcast",
            text="Webcast",
            href_path="/wcc/r/5416059/token",
            context_text="Q2 2026 Results Earnings release Presentation Webcast",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [news_card, webcast],
                lifecycle="replay",
                reference_date=date(2026, 8, 6),
            ),
            webcast,
        )

    def test_replay_prefers_completed_event_evidence_over_fresher_row(self):
        fresh = candidate(
            candidate_id="fresh",
            text="Q2 2026 Earnings Conference Call",
            href_path="/events/event-details/q2-2026-earnings-call",
            context_text="08/04/26 Q2 2026 Earnings Conference Call",
        )
        completed = candidate(
            candidate_id="completed",
            text="Q1 2026 Earnings Conference Call",
            href_path="/events/event-details/q1-2026-earnings-call",
            context_text="05/06/26 Q1 2026 Earnings Conference Call Transcript",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [fresh, completed],
                lifecycle="replay",
                reference_date=date(2026, 8, 7),
            ),
            completed,
        )

    def test_event_heading_does_not_become_playback_control_from_context(self):
        heading = candidate(
            candidate_id="meeting",
            text="Investor Meeting with Management",
            href_path="/events/investor-meeting",
            context_text="March 17, 2026 Webcast",
        )
        earnings_webcast = candidate(
            candidate_id="earnings",
            text="Webcast Q1 2026 Earnings Conference Call",
            href_path="/attendee/earnings",
            context_text="April 30, 2026",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [earnings_webcast, heading],
                lifecycle="replay",
                reference_date=date(2026, 7, 27),
            ),
            earnings_webcast,
        )

    def test_unrelated_webcast_does_not_borrow_nearby_earnings_context(self):
        earnings_webcast = candidate(
            candidate_id="frame-0-element-1",
            text="Webcast Q1 2026 Earnings Conference Call",
            href_path="/attendee/earnings",
            context_text="April 30, 2026 Q1 2026 Earnings Conference Call",
            rect={"x": 0, "y": 100, "width": 200, "height": 20},
        )
        investor_meeting = candidate(
            candidate_id="frame-0-element-2",
            text="Webcast Investor Meeting with Management",
            href_path="/mediaframe/webcast.html",
            context_text="March 17, 2026 Investor Meeting with Management Webcast",
            rect={"x": 0, "y": 180, "width": 200, "height": 20},
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [earnings_webcast, investor_meeting],
                lifecycle="replay",
                reference_date=date(2026, 7, 27),
            ),
            earnings_webcast,
        )

    def test_replay_prefers_quarterly_earnings_over_dated_investor_conference(self):
        investor_conference = candidate(
            candidate_id="conference",
            text="Webcast",
            href_path="/starthere.jsp",
            context_text="June 8, 2026 Goldman Sachs Annual Healthcare Conference Transcript",
        )
        quarterly_earnings = candidate(
            candidate_id="earnings",
            text="Webcast",
            href_path="/Launch/QReg/ShowUUID=quarterly",
            context_text="Pfizer Quarterly Corporate Performance - First Quarter 2026 Press Release",
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [investor_conference, quarterly_earnings],
                lifecycle="replay",
                reference_date=date(2026, 7, 27),
            ),
            quarterly_earnings,
        )

    def test_replay_lifecycle_keeps_attendee_webcast_links_in_navigation(self):
        webcast = candidate(
            candidate_id="attendee",
            text="Click here for webcast",
            href_path="/attendee/391273915",
            in_navigation=True,
        )

        self.assertEqual(
            choose_heuristic_candidate([webcast], lifecycle="replay"),
            webcast,
        )

    def test_heuristic_pairs_generic_webcast_link_with_earnings_title(self):
        earnings_title = candidate(
            candidate_id="frame-0-element-1",
            text="Q2 2026 Earnings Conference Call",
            href_path="/events/q2",
            rect={"x": 0, "y": 100, "width": 300, "height": 30},
            in_navigation=True,
        )
        earnings_webcast = candidate(
            candidate_id="frame-0-element-2",
            text="Listen to Webcast",
            href_path="/mmc/p/q2",
            rect={"x": 0, "y": 145, "width": 150, "height": 24},
            in_navigation=True,
        )
        conference_title = candidate(
            candidate_id="frame-0-element-3",
            text="Healthcare Investor Conference",
            href_path="/events/conference",
            rect={"x": 0, "y": 220, "width": 300, "height": 30},
            in_navigation=True,
        )
        conference_webcast = candidate(
            candidate_id="frame-0-element-4",
            text="Listen to Webcast",
            href_path="/events/conference/webcast",
            rect={"x": 0, "y": 265, "width": 150, "height": 24},
            in_navigation=True,
        )

        self.assertEqual(
            choose_heuristic_candidate(
                [earnings_title, earnings_webcast, conference_title, conference_webcast]
            ),
            earnings_webcast,
        )

    def test_generalized_patterns_reward_verified_replay_actions(self):
        patterns = make_generalized_patterns(
            [
                {
                    "target_text": "Listen to replay",
                    "target_href_path": "/events/q2-webcast",
                    "success_count": 3,
                }
            ]
        )
        replay = candidate(text="Listen to replay", href_path="/events/q3-webcast")
        unrelated = candidate(text="Investor presentation", href_path="/presentations")

        self.assertGreater(generalized_candidate_bonus(replay, patterns), 0)
        self.assertEqual(generalized_candidate_bonus(unrelated, patterns), 0)

    def test_generalized_patterns_are_fallback_only_for_weak_controls(self):
        patterns = make_generalized_patterns(
            [{"target_text": "Listen to replay", "success_count": 2}]
        )
        weak_play = candidate(text="Play recording", href_path="/recording")

        self.assertIsNone(choose_heuristic_candidate([weak_play]))
        self.assertEqual(
            choose_heuristic_candidate([weak_play], patterns),
            weak_play,
        )

    def test_recipe_keeps_multiple_dom_selectors_and_stable_domain_key(self):
        recipe = make_recipe(
            "https://ir.example.com/events?token=secret",
            candidate(),
            strategy="vision",
            confidence=0.88,
        )

        self.assertEqual(recipe.domain, "ir.example.com")
        self.assertEqual(recipe.lifecycle, "unknown")
        self.assertEqual(recipe.selectors[0], "#webcast")
        self.assertEqual(len(recipe.recipe_key), 64)
        self.assertNotIn("token=secret", recipe.database_value()["evidence_json"])

    def test_recipe_key_changes_by_lifecycle(self):
        replay = make_recipe(
            "https://ir.example.com/events",
            candidate(),
            strategy="dom-heuristic",
            lifecycle="replay",
            confidence=0.5,
        )
        live = make_recipe(
            "https://ir.example.com/events",
            candidate(),
            strategy="dom-heuristic",
            lifecycle="live",
            confidence=0.5,
        )

        self.assertNotEqual(replay.recipe_key, live.recipe_key)

    def test_recipe_key_keeps_workflow_stage_separate(self):
        playback = WebcastRecipe(
            domain="ir.example.com",
            selectors=("#webcast",),
            frame_hostname=None,
            target_text="Webcast",
            target_href_path="/webcast",
            strategy="human_workflow",
            lifecycle="replay",
            confidence=0.9,
            evidence={},
            stage="playback",
        )
        event_selection = WebcastRecipe(
            domain="ir.example.com",
            selectors=("#webcast",),
            frame_hostname=None,
            target_text="Webcast",
            target_href_path="/webcast",
            strategy="human_workflow",
            lifecycle="replay",
            confidence=0.9,
            evidence={"workflow_stage": "event_selection"},
            stage="event_selection",
        )

        self.assertNotEqual(playback.recipe_key, event_selection.recipe_key)

    def test_vision_response_parser_accepts_responses_api_output(self):
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"candidate_id":"candidate-1","confidence":0.9,"reason":"live button","x":0,"y":0}',
                        }
                    ]
                }
            ]
        }

        selection = parse_vision_selection(extract_response_text(payload))
        self.assertEqual(selection.candidate_id, "candidate-1")
        self.assertEqual(selection.confidence, 0.9)

    def test_recipe_outcome_reads_context_and_updates_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text(json.dumps({"recipe_id": 42}), encoding="utf-8")
            with mock.patch(
                "data_pipeline.collectors.streams.recipe_outcome.database.record_webcast_recipe_outcome"
            ) as record:
                self.assertTrue(record_context_outcome(path, "success"))

        record.assert_called_once_with(42, success=True, error=None)


if __name__ == "__main__":
    unittest.main()
