import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from data_pipeline.collectors.streams.browser_webcast import (
    ACCESS_BARRIER_PATTERN,
    ALREADY_REGISTERED_PATTERN,
    BrowserWebcastAgent,
    DYNAMIC_LOADING_PATTERN,
    EXPIRED_EVENT_PATTERN,
    HTTP_ACCESS_BARRIER_STATUSES,
    HumanPageAssessment,
    NOT_LIVE_EVENT_PATTERN,
    RESOURCE_NOT_FOUND_PATTERN,
    InvestorProfile,
    PLAY_TEXT_PATTERN,
    REGISTRATION_EMAIL_ERROR_PATTERN,
    REGISTRATION_BARRIER_PATTERN,
    is_positive_registration_consent_text,
    REGISTRATION_FORM_CONTAINER_SELECTORS,
    REGISTRATION_FORM_TEXT_PATTERN,
    WEBCASTS_REGISTRATION_FIELD_SELECTORS,
    WEBCASTS_REGISTRATION_SUBMIT_SELECTOR,
    archive_navigation_url,
    access_fallback_urls,
    default_chromium_executable,
    is_direct_player_url,
    is_audio_priming_player_url,
    is_existing_webinar_login_surface,
    is_event_specific_replay_recipe,
    is_replay_proxy_link,
    is_webcast_player_url,
    is_q4_followup_registration_text,
    is_q4_custom_registration_text,
    is_q4_guest_registration_text,
    MISSING_RESOURCE_URL_PATTERN,
    NON_PLAYBACK_MEDIA_PATH_PATTERN,
    NON_PLAYBACK_DOCUMENT_PATTERN,
    non_earnings_event_reason,
    future_event_date_reason,
    is_media_candidate_url,
    is_non_replay_navigation_link,
    is_non_playback_home_url,
    is_non_playback_product_surface_url,
    is_nonessential_popup_url,
    is_non_playback_surface_url,
    is_open_exchange_registration_url,
    is_playback_control_label,
    load_registration_approval_manifest,
    redact_registration_url,
    registration_url_identity,
    provider_archive_navigation_url,
    REPLAY_EXPANSION_LABEL_PATTERN,
    replay_page_number,
)
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate,
    WebcastRecipe,
    candidate_identity_mismatch,
    event_datetime_from_text,
    live_candidate_identity_confirmation,
)


class BrowserWebcastHelpersTest(unittest.TestCase):
    def test_registration_approval_manifest_matches_destination_and_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as manifest_file:
            json.dump(
                {
                    "approvals": {
                        "DOW": {
                            "approved": True,
                            "destination_url": "https://provider.example.com/register",
                            "prepared_fields": ["email", "first_name"],
                            "consent_selected": True,
                        }
                    }
                },
                manifest_file,
            )
            manifest_file.flush()
            with mock.patch.dict(
                "os.environ",
                {
                    "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true",
                    "WEBCAST_REGISTRATION_REQUIRE_APPROVAL": "true",
                    "WEBCAST_REGISTRATION_APPROVAL_FILE": manifest_file.name,
                },
                clear=False,
            ):
                agent = BrowserWebcastAgent(
                    "DOW",
                    "https://investor.example.com/events",
                )

            self.assertEqual(
                load_registration_approval_manifest(manifest_file.name)["DOW"][
                    "approved"
                ],
                True,
            )
            self.assertIsNone(
                agent._registration_approval_error(
                    "https://provider.example.com/register",
                    ["first_name", "email"],
                    True,
                )
            )
            self.assertIn(
                "destination does not match",
                agent._registration_approval_error(
                    "https://provider.example.com/other",
                    ["first_name", "email"],
                    True,
                ),
            )

    def test_global_registration_permission_does_not_require_manifest(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true",
                "WEBCAST_REGISTRATION_REQUIRE_APPROVAL": "false",
                "WEBCAST_REGISTRATION_APPROVAL_FILE": "",
            },
            clear=False,
        ):
            agent = BrowserWebcastAgent("ADSK", "https://investor.example.com/events")

        self.assertIsNone(
            agent._registration_approval_error(
                "https://provider.example.com/register",
                ["first_name", "email"],
                True,
            )
        )

    def test_registration_url_identity_ignores_auth_query_values(self):
        first = registration_url_identity(
            "https://provider.example.com/register?state=one&lang=en"
        )
        second = registration_url_identity(
            "https://provider.example.com/register?lang=en&state=two"
        )

        self.assertEqual(first, second)

    def test_registration_preview_url_redacts_auth_query_values(self):
        redacted = redact_registration_url(
            "https://provider.example.com/register?code=secret&state=private&lang=en"
        )

        self.assertIn("code=%5BREDACTED%5D", redacted)
        self.assertIn("state=%5BREDACTED%5D", redacted)
        self.assertIn("lang=en", redacted)

    def test_direct_replay_target_is_read_from_environment(self):
        with mock.patch.dict(
            "os.environ",
            {"WEBCAST_DIRECT_TARGET_URL": "https://video.example.com/replay/123"},
            clear=False,
        ):
            agent = BrowserWebcastAgent(
                "DPZ",
                "https://ir.dominos.com/events",
            )

        self.assertEqual(
            agent.direct_target_url,
            "https://video.example.com/replay/123",
        )

    def test_replay_training_allows_newest_event_by_default(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_LIFECYCLE": "replay",
                "WEBCAST_REPLAY_TRAINING_PROXY": "true",
            },
            clear=False,
        ):
            agent = BrowserWebcastAgent("EXPD", "https://investor.example.com/events")
            self.assertEqual(agent._replay_minimum_age_days(), 0)

    def test_live_monitoring_keeps_replay_age_guard(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_LIFECYCLE": "live",
                "WEBCAST_REPLAY_TRAINING_PROXY": "false",
            },
            clear=False,
        ):
            agent = BrowserWebcastAgent("EXPD", "https://investor.example.com/events")
            self.assertEqual(agent._replay_minimum_age_days(), 2)

    def test_live_candidate_exclusion_and_scheduled_date_guard(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_LIFECYCLE": "live",
                "WEBCAST_TARGET_DATE": "2026-08-27",
                "WEBCAST_LIVE_EXCLUDED_URLS": "https://provider.example.com/event-old?token=redacted",
            },
            clear=False,
        ):
            agent = BrowserWebcastAgent("MSFT", "https://investor.example.com/events")

        self.assertTrue(
            agent._is_live_excluded_url(
                "https://provider.example.com/event-old?session=new",
            )
        )
        self.assertFalse(
            agent._is_live_excluded_url("https://provider.example.com/event-current")
        )
        candidate = WebcastCandidate.from_dict(
            {
                "candidate_id": "dated-event",
                "text": "Q4 2026 Earnings Call August 28, 2026",
                "href_path": "/events/q4-2026",
                "tag_name": "a",
            }
        )
        self.assertTrue(agent._live_candidate_date_mismatch(candidate))

    def test_live_candidate_identity_guard_checks_ticker_period_date_and_time(self):
        target_time = datetime(2026, 8, 27, 18, 30, tzinfo=timezone.utc)
        matching = WebcastCandidate.from_dict(
            {
                "candidate_id": "matching-call",
                "text": "Ticker: MSFT Q3 2026 Earnings Call August 27, 2026 2:30 PM ET",
                "href_path": "/events/msft-q3-2026",
                "tag_name": "a",
            }
        )
        wrong_ticker = WebcastCandidate.from_dict(
            {
                "candidate_id": "wrong-ticker",
                "text": "Ticker: AAPL Q3 2026 Earnings Call August 27, 2026 2:30 PM ET",
                "href_path": "/events/aapl-q3-2026",
                "tag_name": "a",
            }
        )
        wrong_time = WebcastCandidate.from_dict(
            {
                "candidate_id": "wrong-time",
                "text": "Ticker: MSFT Q3 2026 Earnings Call August 27, 2026 9:00 AM ET",
                "href_path": "/events/msft-q3-2026",
                "tag_name": "a",
            }
        )

        self.assertIsNone(
            candidate_identity_mismatch(
                matching,
                target_ticker="MSFT",
                target_year=2026,
                target_quarter="Q3",
                target_date=date(2026, 8, 27),
                target_time_utc=target_time,
            )
        )
        self.assertIn(
            "ticker",
            candidate_identity_mismatch(
                wrong_ticker,
                target_ticker="MSFT",
                target_year=2026,
                target_quarter="Q3",
                target_date=date(2026, 8, 27),
                target_time_utc=target_time,
            ),
        )
        self.assertIn(
            "start time",
            candidate_identity_mismatch(
                wrong_time,
                target_ticker="MSFT",
                target_year=2026,
                target_quarter="Q3",
                target_date=date(2026, 8, 27),
                target_time_utc=target_time,
            ),
        )
        parsed_time = event_datetime_from_text("August 27, 2026 2:30 PM ET")
        self.assertIsNotNone(parsed_time)
        self.assertEqual(parsed_time.astimezone(timezone.utc), target_time)

    def test_live_candidate_requires_positive_target_date_evidence(self):
        stale_generic_player = WebcastCandidate.from_dict(
            {
                "candidate_id": "stale-player",
                "text": "Play Video",
                "context_text": "CPRT Conference Call Play Video User Guide",
                "href_path": "/mediaframe/webcast.html?webcastid=old",
                "tag_name": "a",
            }
        )
        current_call = WebcastCandidate.from_dict(
            {
                "candidate_id": "current-call",
                "text": "Q1 FY2027 Earnings Conference Call",
                "context_text": "September 10, 2026 at 5:00 PM ET",
                "href_path": "/events/fy27-q1",
                "tag_name": "a",
            }
        )

        self.assertIsNone(
            live_candidate_identity_confirmation(
                stale_generic_player,
                target_ticker="CPRT",
                target_date=date(2026, 9, 10),
            )
        )
        self.assertIn(
            "target date",
            live_candidate_identity_confirmation(
                current_call,
                target_ticker="CPRT",
                target_date=date(2026, 9, 10),
            ),
        )

    def test_live_identity_does_not_reject_issuer_fiscal_period_label(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_LIFECYCLE": "live",
                "WEBCAST_TARGET_DATE": "2026-09-10",
                "WEBCAST_TARGET_YEAR": "2026",
                "WEBCAST_TARGET_QUARTER": "Q3",
            },
            clear=False,
        ):
            agent = BrowserWebcastAgent("CPRT", "https://ir.example.com/events")
        candidate = WebcastCandidate.from_dict(
            {
                "candidate_id": "fiscal-call",
                "text": "Q1 FY2027 Earnings Call September 10, 2026",
                "href_path": "/events/fy2027-q1",
                "tag_name": "a",
            }
        )

        self.assertIsNone(agent._live_candidate_identity_mismatch(candidate))
        self.assertIsNotNone(agent._live_candidate_identity_confirmation(candidate))

    def test_live_identity_handshake_is_written_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            signal_path = Path(directory) / "target-ready"
            with mock.patch.dict(
                "os.environ",
                {
                    "WEBCAST_LIFECYCLE": "live",
                    "WEBCAST_TARGET_DATE": "2026-09-10",
                    "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false",
                    "WEBCAST_TARGET_IDENTITY_READY_FILE": str(signal_path),
                },
                clear=False,
            ):
                agent = BrowserWebcastAgent(
                    "CPRT",
                    "https://investor.example.com/events",
                )
            self.assertFalse(signal_path.exists())

            agent._mark_live_target_identity_confirmed(
                "target date and earnings context matched"
            )
            self.assertTrue(signal_path.exists())

            agent._reset_live_target_identity_confirmation()
            self.assertFalse(signal_path.exists())

    def test_non_earnings_event_reason_rejects_investor_day(self):
        self.assertEqual(
            non_earnings_event_reason("FOR 2026 INVESTOR DAY"),
            "INVESTOR DAY",
        )
        self.assertIsNone(
            non_earnings_event_reason("Q3 2026 Earnings Conference Call"),
        )
        self.assertEqual(
            non_earnings_event_reason("William Blair Annual Growth Stock Conference"),
            "Annual Growth Stock Conference",
        )
        self.assertEqual(
            non_earnings_event_reason(
                "Q1 FY27 Product & Innovation - Headless 360 + Slack Webinar"
            ),
            "Webinar",
        )
        self.assertIsNone(
            non_earnings_event_reason("Q1 earnings update webinar"),
        )

    def test_q4_custom_registration_step_is_detected(self):
        self.assertTrue(
            is_q4_custom_registration_text(
                "One more thing... Company Name REGISTER FOR THIS EVENT"
            )
        )
        self.assertFalse(
            is_q4_custom_registration_text(
                "Q2 earnings call Company Name REGISTER FOR THIS EVENT"
            )
        )

    def test_q4_guest_registration_step_is_detected(self):
        self.assertTrue(
            is_q4_guest_registration_text(
                "Guest Registration First Name Last Name Email "
                "I am an individual attendee Register for this Event"
            )
        )
        self.assertTrue(
            is_q4_guest_registration_text(
                "Company Name Required Register for this Event"
            )
        )
        self.assertFalse(
            is_q4_guest_registration_text(
                "One more thing... Company Name REGISTER FOR THIS EVENT"
            )
        )

    def test_replay_page_number_reads_accessible_pagination_labels(self):
        self.assertEqual(replay_page_number("2", "Go to page 2"), 2)
        self.assertEqual(replay_page_number("", "Go to page 3"), 3)
        self.assertEqual(replay_page_number(None, "Page 12"), 12)
        self.assertIsNone(replay_page_number("Webcast", "Open event"))

    def test_media_candidate_detection(self):
        self.assertTrue(is_media_candidate_url("https://example.com/audio/playlist.m3u8"))
        self.assertTrue(is_media_candidate_url("https://example.com/video.mp4?token=abc"))
        self.assertFalse(
            is_media_candidate_url(
                "https://wz5a.wsw.com/vod/expired.mp4/manifest.mpd?token=abc"
            )
        )
        self.assertFalse(is_media_candidate_url("https://example.com/investor/events"))
        self.assertFalse(
            is_media_candidate_url(
                "https://browser.events.data.microsoft.com/OneCollector/1.0/?content-type=application/x-json-stream"
            )
        )

    def test_non_event_media_pattern_rejects_banner_assets(self):
        self.assertIsNotNone(
            NON_PLAYBACK_MEDIA_PATH_PATTERN.search(
                "/media/ropertech-v-banner.mp4"
            )
        )
        self.assertIsNone(
            NON_PLAYBACK_MEDIA_PATH_PATTERN.search(
                "/replay/q2-earnings-call.mp4"
            )
        )

    def test_replay_proxy_link_prefers_webcast_over_static_legal_document(self):
        self.assertTrue(
            is_replay_proxy_link(
                "https://edge.media-server.com/mmc/p/w4ht7b4v",
                "Webcast",
            )
        )
        self.assertTrue(
            is_replay_proxy_link(
                "https://kvgo.com/deutsche-bank/mccormick-and-company-inc-june-2026",
                "Webcast",
            )
        )
        self.assertTrue(
            is_webcast_player_url("https://edge.media-server.com/mmc/p/w4ht7b4v")
        )
        self.assertFalse(
            is_replay_proxy_link(
                "https://ir.mccormick.com/static-files/a206dd85-6572-405b-b78b-acc2367a7ce5",
                "Legal disclaimers for dbAccess Global Consumer Conference Webcast Replay",
                type_hint="application/pdf",
                icon_control=True,
            )
        )

    def test_replay_proxy_link_rejects_app_store_surfaces(self):
        self.assertTrue(
            is_non_playback_surface_url("https://play.google.com/store/games")
        )
        self.assertTrue(
            is_non_playback_surface_url("https://apps.apple.com/us/app/example/id1")
        )
        self.assertFalse(
            is_non_playback_surface_url(
                "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4"
            )
        )
        self.assertFalse(
            is_replay_proxy_link(
                "https://play.google.com/store/games",
                "Play Google Play logo",
            )
        )

    def test_open_exchange_registration_surface_is_provider_generic(self):
        self.assertTrue(
            is_open_exchange_registration_url(
                "https://ameren-corporation-second-quarter-2026-earnings-call.open-exchange.net/registration"
            )
        )
        self.assertTrue(
            is_open_exchange_registration_url(
                "https://johnson-controls-q2-2026-earnings.open-exchange.net/registration/"
            )
        )
        self.assertFalse(
            is_open_exchange_registration_url(
                "https://ameren-corporation-second-quarter-2026-earnings-call.open-exchange.net/replay"
            )
        )

    def test_replay_proxy_link_rejects_product_and_home_navigation(self):
        product_url = "https://www.skyworksinc.com/Products/Audio-and-Radio"
        home_url = "https://www.carvana.com/"
        self.assertTrue(
            is_non_playback_product_surface_url(product_url, "Audio And Radio")
        )
        self.assertTrue(
            is_non_playback_home_url(home_url, "Carvana - link to home page")
        )
        self.assertFalse(is_replay_proxy_link(product_url, "Audio And Radio"))
        self.assertFalse(
            is_replay_proxy_link(home_url, "Carvana - link to home page")
        )

    def test_replay_navigation_filter_keeps_event_details_and_players(self):
        self.assertTrue(
            is_non_replay_navigation_link(
                "https://investor.example.com/news-events/events",
                "Events",
            )
        )
        self.assertTrue(
            is_non_replay_navigation_link(
                "https://investor.example.com/news-events/ir-calendar",
                "Events",
            )
        )
        self.assertTrue(
            is_non_replay_navigation_link(
                "https://cts.businesswire.com/ct/CT?id=smartlink&url=https%3A%2F%2Fwww.example.com%2F",
                "Example, Inc.",
            )
        )
        self.assertFalse(
            is_non_replay_navigation_link(
                "https://investor.example.com/events/event-details/q2-2026-earnings",
                "Q2 2026 Earnings",
            )
        )
        self.assertFalse(
            is_non_replay_navigation_link(
                "https://edge.media-server.com/mmc/p/example",
                "Webcast",
            )
        )

    def test_archive_navigation_prefers_event_calendar_path(self):
        event_calendar = WebcastCandidate(
            candidate_id="calendar",
            selectors=("a",),
            frame_hostname=None,
            text="IR Calendar",
            aria_label="",
            title="",
            href_path="/investors/news-events/ir-calendar",
            tag_name="a",
            rect={"x": 0, "y": 0, "width": 10, "height": 10},
        )
        news_events = WebcastCandidate(
            candidate_id="news",
            selectors=("a",),
            frame_hostname=None,
            text="News & Events",
            aria_label="",
            title="",
            href_path="/news-events",
            tag_name="a",
            rect={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        self.assertEqual(
            archive_navigation_url(
                "https://investor.example.com/investors",
                (news_events, event_calendar),
            ),
            "https://investor.example.com/investors/news-events/ir-calendar",
        )

    def test_non_playback_document_pattern_rejects_transcript_assets(self):
        self.assertIsNotNone(
            NON_PLAYBACK_DOCUMENT_PATTERN.search(
                "https://cdn.example.com/webcast_transcript/call.pdf"
            )
        )
        self.assertIsNone(
            NON_PLAYBACK_DOCUMENT_PATTERN.search(
                "https://cdn.example.com/player/stream.m3u8"
            )
        )

    def test_media_candidate_rejects_homepage_loop_video(self):
        self.assertFalse(
            is_media_candidate_url(
                "https://cdn.example.com/homepageloop_updated/homepageloop_updated.mp4"
            )
        )
        self.assertTrue(
            is_media_candidate_url("https://cdn.example.com/webcast/replay.mp4")
        )

    def test_investor_profile_reads_safe_defaults(self):
        profile = InvestorProfile(
            email="",
            password="",
            first_name="Private",
            last_name="Investor",
            company="Private Investor",
        )

        self.assertEqual(profile.first_name, "Private")
        self.assertEqual(profile.company, "Private Investor")
        self.assertEqual(profile.phone_number, "")
        self.assertEqual(profile.industry_affiliation, "Other")
        self.assertEqual(profile.country, "United States")
        self.assertEqual(profile.occupation, "Other")
        self.assertEqual(profile.job_title, "Investor")
        self.assertEqual(profile.attendee_type, "Other")
        self.assertEqual(profile.other_option, "Other")
        self.assertEqual(profile.full_name, "Private Investor")

    def test_investor_profile_keeps_q4_credentials_separate(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_EMAIL": "generic@example.com",
                "WEBCAST_PASSWORD": "generic-secret",
                "WEBCAST_FIRST_NAME": "Generic",
                "WEBCAST_LAST_NAME": "Investor",
                "WEBCAST_PHONE": "01012345678",
                "WEBCAST_OTHER_OPTION": "Other",
                "Q4_EMAIL": "q4@example.com",
                "Q4_PASSWORD": "q4-secret",
                "Q4_FIRST_NAME": "Q4",
                "Q4_LAST_NAME": "Attendee",
            },
            clear=True,
        ):
            profile = InvestorProfile.from_env()

        self.assertEqual(profile.email, "generic@example.com")
        self.assertEqual(profile.password, "generic-secret")
        self.assertEqual(profile.phone_number, "01012345678")
        self.assertEqual(profile.other_option, "Other")
        self.assertEqual(profile.q4_email, "q4@example.com")
        self.assertEqual(profile.q4_password, "q4-secret")
        self.assertEqual(profile.q4_first_name, "Q4")
        self.assertEqual(profile.q4_last_name, "Attendee")

    def test_replay_recipe_is_event_specific_when_it_contains_quarter_and_year(self):
        recipe = WebcastRecipe(
            domain="investors.example.com",
            selectors=("a",),
            frame_hostname=None,
            target_text="Company Q2 2025 Earnings",
            target_href_path="/2q-2025-earnings-conference-call",
            strategy="dom-heuristic",
            lifecycle="replay",
            confidence=0.5,
            evidence={},
        )
        self.assertTrue(is_event_specific_replay_recipe(recipe))

    def test_replay_recipe_without_event_identity_can_be_reused(self):
        recipe = WebcastRecipe(
            domain="investors.example.com",
            selectors=("a[href*='webcast']",),
            frame_hostname=None,
            target_text="Listen to webcast",
            target_href_path="/events-presentations",
            strategy="generalized",
            lifecycle="replay",
            confidence=0.5,
            evidence={},
        )
        self.assertFalse(is_event_specific_replay_recipe(recipe))

    def test_default_chromium_executable_prefers_env(self):
        with mock.patch.dict(
            "os.environ",
            {"PLAYWRIGHT_CHROMIUM_EXECUTABLE": "/custom/chrome"},
        ):
            self.assertEqual(default_chromium_executable(), "/custom/chrome")

    def test_access_barrier_pattern_matches_cdn_denial_page(self):
        self.assertIsNotNone(
            ACCESS_BARRIER_PATTERN.search("Access Denied: You don't have permission to access this server.")
        )
        self.assertIsNotNone(
            ACCESS_BARRIER_PATTERN.search("Performing security verification before continuing.")
        )
        self.assertIsNotNone(
            ACCESS_BARRIER_PATTERN.search(
                "This request was blocked by our security service. Error 15. Powered by Imperva."
            )
        )
        self.assertIn(403, HTTP_ACCESS_BARRIER_STATUSES)
        self.assertIn(429, HTTP_ACCESS_BARRIER_STATUSES)
        self.assertIsNone(ACCESS_BARRIER_PATTERN.search("Investor relations event calendar"))

    def test_dynamic_loading_pattern_only_matches_loading_shells(self):
        self.assertIsNotNone(DYNAMIC_LOADING_PATTERN.search("Loading..."))
        self.assertIsNotNone(DYNAMIC_LOADING_PATTERN.search("Header\nLoading\nFooter"))
        self.assertIsNone(DYNAMIC_LOADING_PATTERN.search("Loading the webcast registration form"))

    def test_already_registered_pattern_requires_email_login(self):
        self.assertIsNotNone(ALREADY_REGISTERED_PATTERN.search("You are already registered!"))
        self.assertIsNone(ALREADY_REGISTERED_PATTERN.search("Already Registered?"))
        self.assertIsNotNone(
            ALREADY_REGISTERED_PATTERN.search("You will receive an email containing login instructions.")
        )

    def test_registration_consent_selects_affirmative_option_only(self):
        self.assertTrue(
            is_positive_registration_consent_text(
                "Yes. I understand that my information will be processed and shared."
            )
        )
        self.assertTrue(is_positive_registration_consent_text('value=yes terms'))
        self.assertFalse(
            is_positive_registration_consent_text(
                "No. I do not want my information processed or shared."
            )
        )

    def test_registration_email_error_pattern_matches_provider_validation(self):
        self.assertIsNotNone(
            REGISTRATION_EMAIL_ERROR_PATTERN.search(
                "Please enter a valid email address. (Error 1022-228581076)"
            )
        )

    def test_existing_webinar_login_surface_requires_attend_action(self):
        self.assertTrue(
            is_existing_webinar_login_surface(
                "Log In Now Email Address Attend Register Now"
            )
        )
        self.assertFalse(
            is_existing_webinar_login_surface(
                "Log In Now Email Address Register Now"
            )
        )

    def test_registration_barrier_pattern_detects_hcaptcha(self):
        self.assertIsNotNone(
            REGISTRATION_BARRIER_PATTERN.search(
                "This site is protected by hCaptcha and its Privacy Policy applies."
            )
        )

    def test_registration_form_text_pattern_detects_label_only_forms(self):
        self.assertIsNotNone(
            REGISTRATION_FORM_TEXT_PATTERN.search(
                "First Name * Last Name * Email Address * Company * Register"
            )
        )

    def test_webcasts_registration_uses_stable_semantic_attributes(self):
        self.assertEqual(REGISTRATION_FORM_CONTAINER_SELECTORS[0], "form#frmRegister")
        self.assertEqual(
            WEBCASTS_REGISTRATION_FIELD_SELECTORS,
            {
                "first_name": "input[title='First Name' i]",
                "last_name": "input[title='Last Name' i]",
                "company": "input[title='Company' i]",
                "email": "input[title='Email' i]",
            },
        )
        self.assertEqual(
            WEBCASTS_REGISTRATION_SUBMIT_SELECTOR,
            "input.buttonSubmit[type='submit'][value='Submit' i]",
        )

    def test_expired_event_pattern_separates_retired_recordings(self):
        self.assertIsNotNone(
            EXPIRED_EVENT_PATTERN.search(
                "The recording of this session is not available any more."
            )
        )
        self.assertIsNotNone(
            EXPIRED_EVENT_PATTERN.search(
                "This presentation has concluded, no replay available."
            )
        )
        self.assertIsNone(
            EXPIRED_EVENT_PATTERN.search(
                "This webinar has ended. Register below to watch it on-demand."
            )
        )

    def test_not_live_event_pattern_detects_scheduled_player_pages(self):
        self.assertIsNotNone(
            NOT_LIVE_EVENT_PATTERN.search(
                "Entry to the live presentation is not yet available. Please come back closer to the scheduled start time."
            )
        )
        self.assertIsNotNone(
            NOT_LIVE_EVENT_PATTERN.search(
                "Thank you for registering! You can access the webcast up to 15 minutes before the start time."
            )
        )
        self.assertIsNotNone(
            NOT_LIVE_EVENT_PATTERN.search(
                "Please return to this page a few minutes before the start of this event."
            )
        )

    def test_resource_not_found_pattern_separates_dead_provider_urls(self):
        self.assertIsNotNone(
            RESOURCE_NOT_FOUND_PATTERN.search(
                "The resource you have requested cannot be found."
            )
        )

    def test_play_text_pattern_does_not_match_overview(self):
        self.assertIsNone(PLAY_TEXT_PATTERN.search("Overview"))
        self.assertIsNotNone(PLAY_TEXT_PATTERN.search("Play webcast"))
        self.assertIsNotNone(PLAY_TEXT_PATTERN.search("View Now"))

    def test_playback_control_label_rejects_navigation_and_downloads(self):
        for label in (
            "Join Our Team",
            "JOIN US",
            "Overview",
            "Download Audio Replay (MP3)",
            "Subscribe to Earnings Conference Call",
            "Privacy Preferences",
            "To listen to the webcast, please register here",
            "Shop Watch",
            "Watch",
            "Webcast",
        ):
            with self.subTest(label=label):
                self.assertFalse(is_playback_control_label(label))

    def test_playback_control_label_keeps_explicit_player_actions(self):
        for label in (
            "Listen to the Webcast",
            "Watch the Replay",
            "View Now",
            "Join the webcast here",
            "Play",
            "Unmute",
            "Enter",
        ):
            with self.subTest(label=label):
                self.assertTrue(is_playback_control_label(label))

    def test_missing_resource_url_pattern_covers_hash_404(self):
        self.assertIsNotNone(MISSING_RESOURCE_URL_PATTERN.search("https://video.example/#/404"))
        self.assertIsNone(MISSING_RESOURCE_URL_PATTERN.search("https://video.example/#/videos/abc"))

    def test_future_event_date_is_not_live_yet(self):
        self.assertIsNotNone(
            future_event_date_reason(
                "John Deere 4Q Earnings Call November 25, 2026 09:00 AM CST",
                reference_date=date(2026, 7, 28),
            )
        )
        self.assertIsNone(
            future_event_date_reason(
                "Q2 Earnings Conference Call July 15, 2026",
                reference_date=date(2026, 7, 28),
            )
        )

    def test_replay_expansion_label_matches_generic_event_row_controls(self):
        for label in ("+", "More Information", "View Details", "Expand"):
            with self.subTest(label=label):
                self.assertIsNotNone(REPLAY_EXPANSION_LABEL_PATTERN.search(label))

        self.assertIsNone(REPLAY_EXPANSION_LABEL_PATTERN.search("Add to Calendar"))

    def test_direct_player_url_recognizes_supported_players(self):
        self.assertTrue(is_direct_player_url("https://www.youtube.com/live/abc"))
        self.assertTrue(is_direct_player_url("https://youtu.be/abc"))
        self.assertTrue(is_audio_priming_player_url("https://edge.media-server.com/mmc/p/abc/"))
        self.assertFalse(is_direct_player_url("https://www.youtube.com/walmart"))
        self.assertFalse(is_direct_player_url("https://www.youtube.com/channel/UC123"))
        self.assertFalse(is_direct_player_url("https://investor.example.com/events"))

    def test_provider_player_url_requires_a_choruscall_identifier(self):
        self.assertTrue(
            is_webcast_player_url(
                "https://event.choruscall.com/mediaframe/webcast.html?webcastid=abc123"
            )
        )
        self.assertFalse(
            is_webcast_player_url("https://event.choruscall.com/mediaframe/webcast.html")
        )

    def test_qualtrics_is_treated_as_nonessential_popup(self):
        self.assertTrue(
            is_nonessential_popup_url(
                "https://uhgenterprise.qualtrics.com/jfe/form/example"
            )
        )
        self.assertFalse(
            is_nonessential_popup_url("https://event.webcasts.com/starthere.jsp")
        )

    def test_provider_archive_fallback_uses_same_site_entrypoint(self):
        self.assertEqual(
            provider_archive_navigation_url(
                "https://ir.thermofisher.com/investors/news-events/news/example"
            ),
            "https://ir.thermofisher.com/investors/news-events/events/default.aspx",
        )
        self.assertIsNone(provider_archive_navigation_url("https://example.com/news"))

    def test_access_fallback_urls_are_explicit_and_same_org(self):
        self.assertIn(
            "https://investors.garmin.com/investors/",
            access_fallback_urls("https://www.garmin.com/investors/"),
        )
        self.assertIn(
            "https://investor.qualcomm.com/news-events/events/default.aspx",
            access_fallback_urls(
                "https://investor.qualcomm.com/news-events/events-disclaimer/default.aspx"
            ),
        )
        self.assertIn(
            "https://firstenergycorp2020index.q4web.com/investor-materials/webcasts-and-presentations/",
            access_fallback_urls(
                "https://investors.firstenergycorp.com/investor-materials/webcasts-and-presentations/"
            ),
        )
        self.assertNotIn(
            "https://other.example/investor-materials/webcasts-and-presentations/",
            access_fallback_urls(
                "https://investors.firstenergycorp.com/investor-materials/webcasts-and-presentations/"
            ),
        )

    def test_registration_submission_is_enabled_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            agent = BrowserWebcastAgent("MSFT", "https://investor.example.com/events")

        self.assertTrue(agent.allow_registration_submission)

    def test_manual_ready_file_is_optional_and_env_configured(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_MANUAL_READY_FILE": "/tmp/manual-ready",
                "WEBCAST_PLAYBACK_READY_FILE": "/tmp/playback-ready",
            },
        ):
            agent = BrowserWebcastAgent("MSFT", "https://investor.example.com/events")

        self.assertEqual(agent.manual_ready_path, Path("/tmp/manual-ready"))
        self.assertEqual(agent.playback_ready_path, Path("/tmp/playback-ready"))
        self.assertGreater(agent.manual_ready_timeout_seconds, 0)

    def test_last_target_url_rejects_social_share_popup(self):
        target_path = Path("/tmp/ew-last-target-test")
        target_path.unlink(missing_ok=True)
        with mock.patch.dict(
            "os.environ",
            {"WEBCAST_LAST_TARGET_URL_FILE": str(target_path)},
        ):
            agent = BrowserWebcastAgent("MSFT", "https://investor.example.com/events")
            agent._record_target_url(
                "https://www.facebook.com/share_channel/?external_share=1"
            )

        self.assertFalse(target_path.exists())

    def test_last_target_url_preserves_direct_event_page_for_retry(self):
        target_path = Path("/tmp/ew-last-target-event-test")
        target_path.unlink(missing_ok=True)
        with mock.patch.dict(
            "os.environ",
            {"WEBCAST_LAST_TARGET_URL_FILE": str(target_path)},
        ):
            agent = BrowserWebcastAgent("EXPD", "https://investor.example.com/events")
            agent._record_target_url(
                "https://investor.example.com/events/q2-2026-earnings-webcast"
            )

        self.assertEqual(
            target_path.read_text(encoding="utf-8"),
            "https://investor.example.com/events/q2-2026-earnings-webcast",
        )
        target_path.unlink(missing_ok=True)

    def test_archive_navigation_prefers_same_site_audio_archive(self):
        candidates = (
            WebcastCandidate(
                candidate_id="events",
                selectors=("a",),
                frame_hostname=None,
                text="Events and Presentations",
                aria_label="",
                title="",
                href_path="/events",
                tag_name="a",
                rect={},
                in_navigation=True,
            ),
            WebcastCandidate(
                candidate_id="archive",
                selectors=("a",),
                frame_hostname=None,
                text="Audio Archives",
                aria_label="",
                title="",
                href_path="/audio-archives",
                tag_name="a",
                rect={},
                in_navigation=True,
            ),
            WebcastCandidate(
                candidate_id="external",
                selectors=("a",),
                frame_hostname=None,
                text="Audio Archives",
                aria_label="",
                title="",
                href_path="https://other.example/audio-archives",
                tag_name="a",
                rect={},
                in_navigation=True,
            ),
        )

        self.assertEqual(
            archive_navigation_url("https://investor.example/news", candidates),
            "https://investor.example/audio-archives",
        )

    def test_archive_navigation_accepts_news_and_events_entrypoint(self):
        candidates = (
            WebcastCandidate(
                candidate_id="news-events",
                selectors=("a",),
                frame_hostname=None,
                text="News & Events",
                aria_label="",
                title="",
                href_path="/news-and-events/default.aspx",
                tag_name="a",
                rect={},
                in_navigation=True,
            ),
        )

        self.assertEqual(
            archive_navigation_url("https://investor.example/overview", candidates),
            "https://investor.example/news-and-events/default.aspx",
        )

    def test_archive_navigation_accepts_plain_events_entrypoint(self):
        candidates = (
            WebcastCandidate(
                candidate_id="events",
                selectors=("a",),
                frame_hostname=None,
                text="Events",
                aria_label="",
                title="",
                href_path="/events",
                tag_name="a",
                rect={},
                in_navigation=True,
            ),
        )

        self.assertEqual(
            archive_navigation_url("https://investor.example/", candidates),
            "https://investor.example/events",
        )


class BrowserPlaybackDetectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_direct_target_retains_page_that_committed_after_timeout(self):
        agent = BrowserWebcastAgent("CCI", "https://investor.example.com/events")
        target_url = "https://investor.example.com/events/event-details/q2-2026"
        page = mock.Mock()
        page.url = target_url
        page.on = mock.Mock()
        page.goto = mock.AsyncMock(side_effect=TimeoutError())
        page.wait_for_load_state = mock.AsyncMock()
        context = mock.Mock()
        context.new_page = mock.AsyncMock(return_value=page)

        with (
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(agent, "accept_cookie_banners", new=mock.AsyncMock()),
            mock.patch.object(agent, "_detect_access_barrier", new=mock.AsyncMock(return_value=None)),
        ):
            opened_page = await agent._open_direct_target_page(context, target_url)

        self.assertIs(opened_page, page)
        self.assertEqual(context.new_page.await_count, 1)
        page.goto.assert_awaited_once()

    def test_live_recipe_lookup_does_not_reuse_replay_recipe(self):
        with mock.patch.dict("os.environ", {"WEBCAST_LIFECYCLE": "live"}):
            agent = BrowserWebcastAgent("NUE", "https://investors.example.com/events")

        self.assertEqual(agent._compatible_recipe_lifecycles(), ("live", "unknown"))

    async def test_expands_replay_event_row_before_rescanning(self):
        with mock.patch.dict("os.environ", {"WEBCAST_LIFECYCLE": "replay"}):
            agent = BrowserWebcastAgent("LOW", "https://example.com/events")
        frame = mock.Mock()
        frame.evaluate = mock.AsyncMock(
            return_value=[{"selector": "#more-info", "label": "More Information"}]
        )
        control = mock.Mock()
        control.is_visible = mock.AsyncMock(return_value=True)
        control.click = mock.AsyncMock()
        locator = mock.Mock()
        locator.first = control
        frame.locator = mock.Mock(return_value=locator)
        page = mock.Mock()
        page.frames = [frame]

        expanded = await agent._expand_replay_event_rows(page)

        self.assertTrue(expanded)
        control.click.assert_awaited_once()

    async def test_cookie_cleanup_closes_standard_legal_dialog(self):
        agent = BrowserWebcastAgent("IDXX", "https://example.com/events")
        body = mock.Mock()
        body.inner_text = mock.AsyncMock(
            return_value="Forward-looking statements and legal disclaimer"
        )
        close_button = mock.Mock()
        close_button.count = mock.AsyncMock(return_value=1)
        close_button.is_visible = mock.AsyncMock(return_value=True)
        close_button.click = mock.AsyncMock()

        def locator(selector):
            if selector == "body":
                return body
            item = mock.Mock()
            item.first = close_button if "aria-label*='Close'" in selector else mock.Mock()
            if item.first is not close_button:
                item.first.count = mock.AsyncMock(return_value=0)
            return item

        frame = mock.Mock()
        frame.locator = mock.Mock(side_effect=locator)
        frame.evaluate = mock.AsyncMock()
        page = mock.Mock()
        page.url = "https://example.com/events"
        page.frames = [frame]
        page.context.pages = [page]

        await agent.accept_cookie_banners(page)

        close_button.click.assert_awaited_once_with(force=True)
        self.assertTrue(
            any("dialog.close" in call.args[0] for call in frame.evaluate.await_args_list)
        )

    async def test_cookie_cleanup_accepts_legal_disclosure_when_required(self):
        agent = BrowserWebcastAgent("HCA", "https://example.com/events")
        body = mock.Mock()
        body.inner_text = mock.AsyncMock(
            return_value="Forward-Looking Statements Cancel Accept"
        )
        accept = mock.Mock()
        accept.count = mock.AsyncMock(return_value=1)
        accept.is_visible = mock.AsyncMock(return_value=True)
        accept.click = mock.AsyncMock()
        accept_locator = mock.Mock(first=accept)
        empty = mock.Mock()
        empty.first = mock.Mock()
        empty.first.count = mock.AsyncMock(return_value=0)

        frame = mock.Mock()
        frame.locator = mock.Mock(
            side_effect=lambda selector: body if selector == "body" else empty
        )
        frame.get_by_role = mock.Mock(return_value=accept_locator)
        frame.evaluate = mock.AsyncMock()
        page = mock.Mock()
        page.url = "https://example.com/events"
        page.frames = [frame]
        page.context.pages = [page]

        await agent.accept_cookie_banners(page)

        accept.click.assert_awaited_once_with(force=True)

    async def test_cookie_cleanup_accepts_explicit_custom_cookie_banner(self):
        agent = BrowserWebcastAgent("CCI", "https://example.com/events")
        body = mock.Mock()
        body.inner_text = mock.AsyncMock(
            return_value="This website uses cookies to improve your experience. I ACCEPT"
        )
        accept = mock.Mock()
        accept.count = mock.AsyncMock(return_value=1)
        accept.is_visible = mock.AsyncMock(return_value=True)
        accept.click = mock.AsyncMock()
        accept_locator = mock.Mock(first=accept)
        empty = mock.Mock()
        empty.first = mock.Mock()
        empty.first.count = mock.AsyncMock(return_value=0)

        frame = mock.Mock()
        frame.locator = mock.Mock(
            side_effect=lambda selector: body if selector == "body" else empty
        )
        frame.get_by_role = mock.Mock(return_value=accept_locator)
        frame.evaluate = mock.AsyncMock()
        page = mock.Mock()
        page.url = "https://example.com/events"
        page.frames = [frame]
        page.context.pages = [page]

        await agent.accept_cookie_banners(page)

        accept.click.assert_awaited_once_with(force=True)

    async def test_cookie_cleanup_follows_webcast_disclosure_continue(self):
        agent = BrowserWebcastAgent("IDXX", "https://example.com/events")
        body = mock.Mock()
        body.inner_text = mock.AsyncMock(
            return_value="Forward-looking statements. Continue to webcast."
        )
        continuation = mock.Mock()
        continuation.count = mock.AsyncMock(return_value=1)
        continuation.is_visible = mock.AsyncMock(return_value=True)
        continuation.get_attribute = mock.AsyncMock(
            side_effect=lambda name: (
                "https://event.webcasts.example/starthere" if name == "data-webcast-url" else ""
            )
        )
        continuation.inner_text = mock.AsyncMock(return_value="Continue")
        continuation.click = mock.AsyncMock()
        close_button = mock.Mock()
        close_button.count = mock.AsyncMock(return_value=1)
        close_button.is_visible = mock.AsyncMock(return_value=True)
        close_button.click = mock.AsyncMock()

        def locator(selector):
            if selector == "body":
                return body
            item = mock.Mock()
            if selector == "[data-webcast-url]":
                item.first = continuation
            elif "aria-label*='Close'" in selector:
                item.first = close_button
            else:
                item.first = mock.Mock()
                item.first.count = mock.AsyncMock(return_value=0)
            return item

        frame = mock.Mock()
        frame.locator = mock.Mock(side_effect=locator)
        frame.evaluate = mock.AsyncMock()
        page = mock.Mock()
        page.url = "https://example.com/events"
        page.frames = [frame]
        page.context.pages = [page]

        await agent.accept_cookie_banners(page)

        continuation.click.assert_awaited_once_with(force=True)
        close_button.click.assert_not_awaited()

    async def test_cookie_cleanup_opens_hidden_hash_webcast_target(self):
        agent = BrowserWebcastAgent("IDXX", "https://example.com/events")
        body = mock.Mock()
        body.inner_text = mock.AsyncMock(return_value="Event details")
        continuation = mock.Mock()
        continuation.count = mock.AsyncMock(return_value=1)
        continuation.is_visible = mock.AsyncMock(return_value=False)
        continuation.get_attribute = mock.AsyncMock(
            side_effect=lambda name: (
                "https://event.webcasts.example/starthere" if name == "data-webcast-url" else ""
            )
        )
        continuation.inner_text = mock.AsyncMock(return_value="Continue")
        frame = mock.Mock()
        webcast_locator = mock.Mock(first=continuation)
        webcast_locator.count = mock.AsyncMock(return_value=1)
        frame.locator = mock.Mock(
            side_effect=lambda selector: (
                body if selector == "body" else webcast_locator
            )
        )
        frame.evaluate = mock.AsyncMock()
        target = mock.Mock()
        target.on = mock.Mock()
        target.goto = mock.AsyncMock()
        context = mock.Mock()
        context.pages = []
        context.new_page = mock.AsyncMock(return_value=target)
        page = mock.Mock()
        page.url = "https://example.com/events#webcast-popup-123"
        page.frames = [frame]
        page.context = context
        context.pages = [page]

        await agent.accept_cookie_banners(page)

        context.new_page.assert_awaited_once()
        target.goto.assert_awaited_once_with(
            "https://event.webcasts.example/starthere",
            wait_until="domcontentloaded",
            timeout=agent.page_ready_timeout_ms,
        )

    async def test_opens_latest_year_inside_archived_events(self):
        with mock.patch.dict("os.environ", {"WEBCAST_LIFECYCLE": "replay"}):
            agent = BrowserWebcastAgent("EL", "https://example.com/events")
        current = mock.Mock()
        current.is_visible = mock.AsyncMock(return_value=True)
        current.inner_text = mock.AsyncMock(return_value="2026")
        current.evaluate = mock.AsyncMock(return_value=True)
        current.scroll_into_view_if_needed = mock.AsyncMock()
        current.click = mock.AsyncMock()
        older = mock.Mock()
        older.is_visible = mock.AsyncMock(return_value=True)
        older.inner_text = mock.AsyncMock(return_value="2025")
        older.evaluate = mock.AsyncMock(return_value=True)
        older.scroll_into_view_if_needed = mock.AsyncMock()
        older.click = mock.AsyncMock()
        controls = mock.Mock()
        controls.count = mock.AsyncMock(return_value=2)
        controls.nth = mock.Mock(side_effect=[current, older])
        controls.filter = mock.Mock(return_value=controls)
        frame = mock.Mock()
        frame.locator = mock.Mock(return_value=controls)
        page = mock.Mock()
        page.frames = [frame]

        with mock.patch.object(
            agent,
            "accept_cookie_banners",
            new=mock.AsyncMock(),
        ):
            activated = await agent._activate_replay_archive_year(page)

        self.assertTrue(activated)
        current.click.assert_awaited_once()
        older.click.assert_not_awaited()

    async def test_youtube_audio_priming_uses_trusted_mute_toggle(self):
        agent = BrowserWebcastAgent("MDT", "https://www.youtube.com/live/example")
        video = mock.Mock()
        video.count = mock.AsyncMock(return_value=1)
        video.hover = mock.AsyncMock()
        video.evaluate = mock.AsyncMock(side_effect=[True, False])
        video.click = mock.AsyncMock()
        mute_button = mock.Mock()
        mute_button.count = mock.AsyncMock(return_value=1)
        mute_button.is_visible = mock.AsyncMock(return_value=True)
        mute_button.get_attribute = mock.AsyncMock(
            side_effect=lambda name: "Mute (m)" if name == "aria-label" else None
        )
        mute_button.click = mock.AsyncMock()
        video_locator = mock.Mock()
        video_locator.first = video
        mute_locator = mock.Mock()
        mute_locator.first = mute_button
        page = mock.Mock()
        page.url = "https://www.youtube.com/live/example"
        page.context.pages = []
        page.locator = mock.Mock(side_effect=[video_locator, mute_locator])

        await agent._prime_direct_player_audio(page)

        self.assertEqual(mute_button.click.await_count, 2)
        self.assertEqual(video.click.await_count, 2)
        self.assertIn(page.url, agent._direct_audio_primed_urls)

    async def test_playback_control_is_scrolled_before_click(self):
        agent = BrowserWebcastAgent("MSFT", "https://example.com/events")
        control = mock.Mock()
        control.scroll_into_view_if_needed = mock.AsyncMock()
        control.click = mock.AsyncMock()

        clicked = await agent._click_playback_control(
            control,
            "Play Earnings Call FY26 Q4",
        )

        self.assertTrue(clicked)
        control.scroll_into_view_if_needed.assert_awaited_once()
        control.click.assert_awaited_once()

    async def test_retries_late_shaka_control_after_frame_render(self):
        agent = BrowserWebcastAgent("MSFT", "https://example.com/events")
        frame = mock.Mock()
        control = mock.Mock()
        control.is_visible = mock.AsyncMock(return_value=True)
        control.inner_text = mock.AsyncMock(return_value="Play video")
        control.get_attribute = mock.AsyncMock(
            side_effect=lambda name: {
                "aria-label": "Play Earnings Call FY26 Q4",
                "title": "Play Earnings Call FY26 Q4",
            }.get(name)
        )
        control.scroll_into_view_if_needed = mock.AsyncMock()
        control.click = mock.AsyncMock()
        controls = mock.Mock()
        controls.count = mock.AsyncMock(return_value=1)
        controls.nth = mock.Mock(return_value=control)
        frame.locator = mock.Mock(return_value=controls)
        page = mock.Mock()
        page.frames = [frame]
        page.context.pages = [page]

        with mock.patch.object(
            agent,
            "_wait_for_active_playback",
            new=mock.AsyncMock(return_value="visible pause control"),
        ):
            activated = await agent._retry_shaka_playback_control(
                page,
                include_context_pages=False,
                timeout_seconds=1,
            )

        self.assertTrue(activated)
        control.click.assert_awaited_once()

    async def test_detects_visible_pause_control_as_active_playback(self):
        agent = BrowserWebcastAgent("ISRG", "https://example.com/webcast")
        frame = mock.Mock()
        frame.evaluate = mock.AsyncMock(return_value="visible pause control")
        page = mock.Mock()
        page.frames = [frame]

        reason = await agent.detect_active_playback(page)

        self.assertEqual(reason, "visible pause control")

    async def test_detects_login_route_as_authentication_barrier(self):
        agent = BrowserWebcastAgent("DG", "https://example.com/events")
        page = mock.Mock()
        page.url = "https://www.webcast-eqs.com/login/dollargeneral20250313"

        barrier = await agent._detect_access_barrier(page)

        self.assertEqual(barrier, "AUTH_REQUIRED authentication/login surface")

    async def test_detects_email_login_form_as_authentication_barrier(self):
        agent = BrowserWebcastAgent("IBKR", "https://example.com/events")
        page = mock.Mock()
        page.url = "https://bofa.veracast.com/webcasts/example.cfm"
        page.evaluate = mock.AsyncMock(return_value={
            'body_text': 'Please log in to access the webcast E-mail Login',
            'captcha_gate': False, 'text_available': True,
        })

        barrier = await agent._detect_access_barrier(page)

        self.assertEqual(barrier, "AUTH_REQUIRED authentication/login form")

    async def test_detects_security_verification_inside_frame_as_access_barrier(self):
        agent = BrowserWebcastAgent("SYK", "https://example.com/events")
        page = mock.Mock()
        page.url = "https://example.com/webcast"
        page.evaluate = mock.AsyncMock(return_value={
            'body_text': '', 'captcha_gate': False, 'text_available': True,
        })
        frame = mock.Mock()
        frame.parent_frame = mock.Mock(parent_frame=None)
        embedding = mock.Mock()
        embedding.evaluate = mock.AsyncMock(return_value={
            'visible': True, 'relevant': True, 'reason': 'visible_flow_embedding',
        })
        embedding.dispose = mock.AsyncMock()
        frame.frame_element = mock.AsyncMock(return_value=embedding)
        frame.evaluate = mock.AsyncMock(return_value={
            'body_text': 'Performing security verification before continuing',
            'captcha_gate': False, 'text_available': True,
        })
        page.frames = [page, frame]

        barrier = await agent._detect_access_barrier(page)

        self.assertEqual(barrier, "Performing security verification")

    async def test_detects_webcaster_no_longer_available_surface(self):
        agent = BrowserWebcastAgent("BX", "https://example.com/events")
        page = mock.Mock()
        frame = mock.Mock()
        frame.locator.return_value.inner_text = mock.AsyncMock(
            return_value="WebcastNoLongerAvailable"
        )
        page.frames = [frame]

        reason = await agent._detect_expired_event(page)

        self.assertEqual(reason, "WebcastNoLongerAvailable")

    async def test_active_playback_detector_accepts_advancing_media_clock(self):
        agent = BrowserWebcastAgent("NFLX", "https://example.com/webcast")
        frame = mock.Mock()
        frame.evaluate = mock.AsyncMock(return_value="video element is playing unmuted volume=1 time=34")
        page = mock.Mock()
        page.frames = [frame]

        reason = await agent.detect_active_playback(page)

        self.assertIn("video element is playing", reason)
        script = frame.evaluate.await_args.args[0]
        self.assertIn("currentTime > 0.25", script)

    async def test_trigger_accepts_player_that_is_already_active(self):
        agent = BrowserWebcastAgent("ISRG", "https://example.com/webcast")
        page = mock.Mock()
        with mock.patch.object(
            agent,
            "detect_active_playback",
            new=mock.AsyncMock(return_value="audio element is playing"),
        ):
            triggered = await agent.trigger_media_playback(page)

        self.assertTrue(triggered)

    async def test_trigger_defers_to_os_audio_after_icon_control_click(self):
        agent = BrowserWebcastAgent("LOW", "https://example.com/webcast")
        frame = mock.Mock()
        button = mock.Mock()
        button.is_visible = mock.AsyncMock(return_value=True)
        button.inner_text = mock.AsyncMock(return_value="")
        button.get_attribute = mock.AsyncMock(
            side_effect=lambda name: "Play webcast" if name == "aria-label" else None
        )
        button.click = mock.AsyncMock()
        controls = mock.Mock()
        controls.count = mock.AsyncMock(return_value=1)
        controls.nth = mock.Mock(return_value=button)
        preferred_controls = mock.Mock()
        preferred_controls.count = mock.AsyncMock(return_value=0)
        def locate(selector):
            if "shaka-load-player-btn" in selector:
                return preferred_controls
            return controls

        frame.locator = mock.Mock(side_effect=locate)
        page = mock.Mock()
        page.frames = [frame]
        page.wait_for_selector = mock.AsyncMock()

        with (
            mock.patch.object(agent, "_prime_direct_player_audio", new=mock.AsyncMock()),
            mock.patch.object(agent, "detect_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(agent, "_wait_for_active_playback", new=mock.AsyncMock(return_value=None)),
        ):
            triggered = await agent.trigger_media_playback(page)

        self.assertTrue(triggered)
        button.click.assert_awaited_once()

    async def test_trigger_ignores_webcast_anchor_outside_player_container(self):
        agent = BrowserWebcastAgent("MS", "https://example.com/events")
        frame = mock.Mock()
        anchor = mock.Mock()
        anchor.is_visible = mock.AsyncMock(return_value=True)
        anchor.get_attribute = mock.AsyncMock(return_value="")
        anchor.inner_text = mock.AsyncMock(return_value="Listen To Our Podcasts")
        anchor.evaluate = mock.AsyncMock(return_value=True)
        anchor.click = mock.AsyncMock()
        controls = mock.Mock()
        controls.count = mock.AsyncMock(return_value=1)
        controls.nth = mock.Mock(return_value=anchor)
        preferred_controls = mock.Mock()
        preferred_controls.count = mock.AsyncMock(return_value=0)

        def locate(selector):
            if "shaka-load-player-btn" in selector:
                return preferred_controls
            return controls

        frame.locator = mock.Mock(side_effect=locate)
        frame.evaluate = mock.AsyncMock(return_value=False)
        page = mock.Mock()
        page.frames = [frame]
        page.wait_for_selector = mock.AsyncMock()

        with (
            mock.patch.object(agent, "_prime_direct_player_audio", new=mock.AsyncMock()),
            mock.patch.object(agent, "_prime_media_audio", new=mock.AsyncMock()),
            mock.patch.object(agent, "detect_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(agent, "_wait_for_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(agent, "_retry_shaka_playback_control", new=mock.AsyncMock(return_value=False)),
        ):
            triggered = await agent.trigger_media_playback(page)

        self.assertFalse(triggered)
        anchor.click.assert_not_awaited()

    async def test_shaka_retry_uses_keyboard_activation_after_click_is_not_confirmed(self):
        agent = BrowserWebcastAgent("MSFT", "https://example.com/webcast")
        frame = mock.Mock()
        button = mock.Mock()
        button.is_visible = mock.AsyncMock(return_value=True)
        button.inner_text = mock.AsyncMock(return_value="Play Earnings Call")
        button.get_attribute = mock.AsyncMock(return_value=None)
        button.scroll_into_view_if_needed = mock.AsyncMock()
        button.click = mock.AsyncMock()
        button.press = mock.AsyncMock()
        controls = mock.Mock()
        controls.count = mock.AsyncMock(return_value=1)
        controls.nth = mock.Mock(return_value=button)
        frame.locator = mock.Mock(return_value=controls)
        page = mock.Mock()
        page.frames = [frame]
        page.context.pages = [page]

        with mock.patch.object(
            agent,
            "_wait_for_active_playback",
            new=mock.AsyncMock(side_effect=[None, "visible pause control"]),
        ) as wait_for_playback:
            triggered = await agent._retry_shaka_playback_control(
                page,
                include_context_pages=False,
                timeout_seconds=1,
            )

        self.assertTrue(triggered)
        button.click.assert_awaited_once()
        button.press.assert_awaited_once_with("Space", timeout=3000)
        self.assertEqual(wait_for_playback.await_count, 2)

    async def test_registered_playback_rechecks_new_player_page(self):
        agent = BrowserWebcastAgent("LOW", "https://example.com/webcast")
        source_page = mock.Mock()
        source_page.is_closed = mock.Mock(return_value=False)
        player_page = mock.Mock()
        player_page.is_closed = mock.Mock(return_value=False)
        context = mock.Mock()
        context.pages = [source_page, player_page]
        agent._registration_target_page = player_page

        with (
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(agent, "accept_cookie_banners", new=mock.AsyncMock()),
            mock.patch.object(
                agent,
                "_apply_human_workflow",
                new=mock.AsyncMock(return_value=(player_page, True)),
            ) as apply_workflow,
            mock.patch.object(agent, "detect_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(agent, "trigger_media_playback", new=mock.AsyncMock(return_value=True)) as trigger,
            mock.patch.object(agent, "_try_media_candidate_playback", new=mock.AsyncMock(return_value=None)),
        ):
            triggered, target_page = await agent._activate_registered_playback(
                context,
                source_page,
            )

        self.assertTrue(triggered)
        self.assertIs(target_page, player_page)
        apply_workflow.assert_awaited_once_with(player_page, stage="playback")
        trigger.assert_awaited_once_with(
            player_page,
            page_scope_only=True,
            require_active_confirmation=True,
        )

    async def test_registered_playback_finds_player_page_open_before_activation(self):
        agent = BrowserWebcastAgent("LOW", "https://example.com/webcast")
        agent.post_registration_playback_wait_seconds = 1
        source_page = mock.Mock()
        source_page.is_closed = mock.Mock(return_value=False)
        player_page = mock.Mock()
        player_page.is_closed = mock.Mock(return_value=False)
        context = mock.Mock()
        context.pages = [source_page, player_page]

        async def apply_workflow(candidate_page, *, stage):
            return candidate_page, False

        async def trigger_playback(candidate_page, **kwargs):
            return candidate_page is player_page

        with (
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(agent, "accept_cookie_banners", new=mock.AsyncMock()),
            mock.patch.object(
                agent,
                "_apply_human_workflow",
                new=mock.AsyncMock(side_effect=apply_workflow),
            ),
            mock.patch.object(agent, "detect_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(
                agent,
                "trigger_media_playback",
                new=mock.AsyncMock(side_effect=trigger_playback),
            ) as trigger,
            mock.patch.object(agent, "_try_media_candidate_playback", new=mock.AsyncMock(return_value=None)),
        ):
            triggered, target_page = await agent._activate_registered_playback(
                context,
                source_page,
            )

        self.assertTrue(triggered)
        self.assertIs(target_page, player_page)
        self.assertEqual(trigger.await_count, 2)
        self.assertEqual(trigger.await_args_list[0].args[0], source_page)
        self.assertEqual(trigger.await_args_list[1].args[0], player_page)

    async def test_registered_playback_stops_when_player_page_is_access_blocked(self):
        agent = BrowserWebcastAgent("LOW", "https://example.com/webcast")
        source_page = mock.Mock()
        source_page.is_closed = mock.Mock(return_value=False)
        context = mock.Mock()
        context.pages = [source_page]

        with (
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(agent, "accept_cookie_banners", new=mock.AsyncMock()),
            mock.patch.object(
                agent,
                "_detect_access_barrier",
                new=mock.AsyncMock(return_value="verify you are human"),
            ),
            mock.patch.object(
                agent,
                "_apply_human_workflow",
                new=mock.AsyncMock(return_value=(source_page, False)),
            ),
            mock.patch.object(agent, "trigger_media_playback", new=mock.AsyncMock()) as trigger,
        ):
            triggered, target_page = await agent._activate_registered_playback(
                context,
                source_page,
            )

        self.assertFalse(triggered)
        self.assertIs(target_page, source_page)
        self.assertEqual(agent._page_barrier, "verify you are human")
        trigger.assert_not_awaited()

    async def test_registered_playback_retries_same_page_after_late_render(self):
        agent = BrowserWebcastAgent("LOW", "https://example.com/webcast")
        agent.post_registration_playback_wait_seconds = 5
        source_page = mock.Mock()
        source_page.is_closed = mock.Mock(return_value=False)
        context = mock.Mock()
        context.pages = [source_page]
        agent._registration_target_page = source_page

        async def trigger_once_then_succeed(*args, **kwargs):
            if trigger.call_count == 1:
                return False
            return True

        with (
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(agent, "accept_cookie_banners", new=mock.AsyncMock()),
            mock.patch.object(
                agent,
                "_apply_human_workflow",
                new=mock.AsyncMock(return_value=(source_page, False)),
            ),
            mock.patch.object(agent, "detect_active_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.object(
                agent,
                "trigger_media_playback",
                new=mock.AsyncMock(side_effect=trigger_once_then_succeed),
            ) as trigger,
            mock.patch.object(agent, "_try_media_candidate_playback", new=mock.AsyncMock(return_value=None)),
            mock.patch.dict("os.environ", {"WEBCAST_PLAYBACK_RETRY_INTERVAL_SECONDS": "1"}),
        ):
            triggered, target_page = await agent._activate_registered_playback(
                context,
                source_page,
            )

        self.assertTrue(triggered)
        self.assertIs(target_page, source_page)
        self.assertEqual(trigger.await_count, 2)

    async def test_registration_handler_returns_after_timeout(self):
        agent = BrowserWebcastAgent("ISRG", "https://example.com/webcast")
        agent.registration_timeout_seconds = 0.01

        async def never_finishes(*args, **kwargs):
            await asyncio.sleep(1)
            return True

        with mock.patch.object(
            agent,
            "fill_registration_form",
            side_effect=never_finishes,
        ):
            handled = await agent.handle_registration_form(
                mock.Mock(),
                TimeoutError,
            )

        self.assertFalse(handled)

    async def test_newsletter_forms_are_not_webcast_registration(self):
        agent = BrowserWebcastAgent("MRNA", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = "https://investor.example.com/events"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 3,
                "identity_field_count": 0,
                "email_field_count": 2,
                "submit_labels": ["Subscribe"],
                "form_text": "Email Alerts Subscribe to investor news",
                "local_form_context": "Investor Email Alerts",
                "body_text": "Email Alerts Subscribe to investor news",
                "event_specific": False,
                "subscription_only": True,
            }
        )

        self.assertFalse(await agent._has_registration_form_in_target(target))

        error_target = mock.Mock()
        error_target.url = "https://irreach.com/subscribe_error/2637/2/"
        error_target.evaluate = mock.AsyncMock()
        self.assertFalse(await agent._has_registration_form_in_target(error_target))
        error_target.evaluate.assert_not_awaited()

    async def test_footer_newsletter_submit_is_not_registration_when_event_links_exist(self):
        """Page-level webcast links must not turn a footer alert form into a gate."""
        agent = BrowserWebcastAgent("BLDR", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = "https://investor.example.com/events"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 7,
                "identity_field_count": 0,
                "email_field_count": 1,
                "submit_labels": ["Submit"],
                "form_text": "Enter Your Email Address Submit",
                "local_form_context": "Investor Email Alerts Mailing list selection is required",
                "body_text": "Webcast Q2 Earnings Conference Call Investor Email Alerts",
                "event_specific": True,
                "subscription_only": False,
                "webcasts_registration_form": False,
            }
        )

        self.assertFalse(await agent._has_registration_form_in_target(target))

    async def test_search_and_subscribe_form_is_not_registration_when_event_text_exists(self):
        """Nearby webcast text must not classify Visa's site-search form as a gate."""
        agent = BrowserWebcastAgent("V", "https://investor.example.com/")
        target = mock.Mock()
        target.url = "https://investor.example.com/"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 9,
                "identity_field_count": 1,
                "email_field_count": 1,
                "submit_labels": ["Search visa.com", "Subscribe"],
                "form_text": "Q3 Visa Earnings Conference Call Search Subscribe",
                "local_form_context": "",
                "body_text": "Q3 Visa Earnings Conference Call Listen to webcast",
                "event_specific": True,
                "subscription_only": False,
                "webcasts_registration_form": False,
            }
        )

        self.assertFalse(await agent._has_registration_form_in_target(target))

    async def test_identity_and_email_submit_form_is_webcast_registration(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = "https://event.example.com/archive"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 3,
                "identity_field_count": 2,
                "email_field_count": 1,
                "submit_labels": ["Submit"],
                "form_text": "Name Email Company Submit",
                "local_form_context": "Event registration",
                "body_text": "Name Email Company Submit",
                "event_specific": False,
                "subscription_only": False,
            }
        )

        self.assertTrue(await agent._has_registration_form_in_target(target))

    async def test_existing_webinar_login_surface_is_webcast_registration(self):
        agent = BrowserWebcastAgent("RCL", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = "https://app.webinar.net/mqdQBo1Mn70"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 1,
                "identity_field_count": 0,
                "email_field_count": 1,
                "submit_labels": ["Attend"],
                "form_text": "Log In Now Email Address Attend",
                "local_form_context": "",
                "body_text": "",
                "event_specific": False,
                "subscription_only": False,
                "existing_webinar_login": True,
            }
        )

        self.assertTrue(await agent._has_registration_form_in_target(target))

    async def test_open_exchange_registration_form_is_detected_from_provider_surface(self):
        agent = BrowserWebcastAgent("AEE", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = (
            "https://ameren-corporation-second-quarter-2026-earnings-call."
            "open-exchange.net/registration"
        )
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 5,
                "identity_field_count": 3,
                "email_field_count": 1,
                "submit_labels": ["Register"],
                "form_text": "Register First Name Last Name Email Organization Affiliation",
                "local_form_context": "",
                "body_text": "Ameren Corporation Earnings Call Register",
                "event_specific": False,
                "subscription_only": False,
                "webcasts_registration_form": False,
            }
        )

        self.assertTrue(await agent._has_registration_form_in_target(target))

    async def test_metameetings_guest_audio_gate_is_webcast_registration(self):
        agent = BrowserWebcastAgent("APTV", "https://ir.aptiv.com/events")
        target = mock.Mock()
        target.url = (
            "https://jpmorgan.metameetings.net/events/auto26/"
            "sessions/319512-aptiv/webcast/public/signin"
        )
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 4,
                "identity_field_count": 3,
                "email_field_count": 1,
                "submit_labels": ["Sign In"],
                "form_text": "First Time Visitor Email First Name Last Name Company Sign In",
                "local_form_context": "General Access Returning Visitor",
                "body_text": "Signing in through this page provides access to the audio stream of this session only.",
                "event_specific": False,
                "metameetings_guest_access": True,
                "subscription_only": False,
                "webcasts_registration_form": False,
            }
        )

        self.assertTrue(await agent._has_registration_form_in_target(target))

    async def test_webcasts_frm_register_marker_handles_dynamic_field_names(self):
        agent = BrowserWebcastAgent("AON", "https://ir.aon.com/events-and-presentations")
        target = mock.Mock()
        target.url = "https://event.webcasts.com/starthere.jsp?ei=1764867"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 4,
                "identity_field_count": 0,
                "email_field_count": 0,
                "submit_labels": ["Submit"],
                "form_text": "frmRegister buttonSubmit",
                "local_form_context": "",
                "body_text": "",
                "event_specific": False,
                "subscription_only": False,
                "webcasts_registration_form": True,
            }
        )

        self.assertTrue(await agent._has_registration_form_in_target(target))

    async def test_empty_webcasts_frm_register_marker_is_not_registration(self):
        agent = BrowserWebcastAgent("HONA", "https://investor.honeywell.com/events")
        target = mock.Mock()
        target.url = "https://investor.honeywell.com/events/event-details/q2-2026"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 0,
                "identity_field_count": 0,
                "email_field_count": 0,
                "submit_labels": [],
                "form_text": "frmRegister",
                "local_form_context": "",
                "body_text": "Q2 Earnings Conference Call Webcast",
                "event_specific": True,
                "subscription_only": False,
                "webcasts_registration_form": False,
            }
        )

        self.assertFalse(await agent._has_registration_form_in_target(target))

    def test_q4_guest_gate_includes_link_variant(self):
        source = Path(
            "data_pipeline/collectors/streams/browser/registration.py"
        ).read_text(encoding="utf-8")
        self.assertIn("a:has-text('Continue without a Q4 account')", source)

    def test_q4_followup_registration_step_is_detected(self):
        self.assertTrue(
            is_q4_followup_registration_text(
                "One more thing... Attendee Type (Required) REGISTER FOR THIS EVENT"
            )
        )
        self.assertFalse(
            is_q4_followup_registration_text(
                "Guest Registration First Name Email Register for this Event"
            )
        )

    async def test_email_alert_registration_and_login_form_is_not_event_registration(self):
        agent = BrowserWebcastAgent("EL", "https://investor.example.com/events")
        target = mock.Mock()
        target.url = "https://investor.example.com/events"
        target.evaluate = mock.AsyncMock(
            return_value={
                "gate_labels": [],
                "field_count": 4,
                "identity_field_count": 0,
                "email_field_count": 2,
                "submit_labels": ["Register", "Login"],
                "form_text": "Events reminders Email Register Login",
                "local_form_context": "Archived Events",
                "body_text": "Upcoming and archived events",
                "event_specific": True,
                "subscription_only": False,
            }
        )

        self.assertFalse(await agent._has_registration_form_in_target(target))

    async def test_registration_safe_mode_does_not_fill_or_submit(self):
        with mock.patch.dict(
            "os.environ",
            {"WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "false"},
        ):
            agent = BrowserWebcastAgent("ISRG", "https://example.com/webcast")
        page = mock.Mock()

        with (
            mock.patch.object(
                agent,
                "has_registration_form",
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                agent,
                "fill_registration_form",
                new=mock.AsyncMock(),
            ) as fill_form,
        ):
            handled = await agent.handle_registration_form(page, TimeoutError)

        self.assertFalse(handled)
        self.assertEqual(
            agent._registration_error(),
            "REGISTRATION_REQUIRED registration submission is disabled",
        )
        fill_form.assert_not_awaited()

    async def test_registration_fill_guard_blocks_q4_gate_before_any_click(self):
        with mock.patch.dict(
            "os.environ",
            {"WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "false"},
        ):
            agent = BrowserWebcastAgent("BA", "https://example.com/webcast")
        page = mock.Mock()
        page.wait_for_selector = mock.AsyncMock()

        with mock.patch.object(
            agent,
            "accept_cookie_banners",
            new=mock.AsyncMock(),
        ) as accept_cookies:
            handled = await agent.fill_registration_form(page, TimeoutError)

        self.assertFalse(handled)
        self.assertEqual(
            agent._registration_error(),
            "REGISTRATION_REQUIRED registration submission is disabled",
        )
        accept_cookies.assert_not_awaited()

    async def test_non_earnings_detection_ignores_background_tabs(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        current_body = mock.Mock()
        current_body.inner_text = mock.AsyncMock(
            return_value="First Name Last Name Email Company Register"
        )
        current_frame = mock.Mock()
        current_frame.locator = mock.Mock(return_value=current_body)
        background_body = mock.Mock()
        background_body.inner_text = mock.AsyncMock(
            return_value="Mizuho Technology Conference"
        )
        background_frame = mock.Mock()
        background_frame.locator = mock.Mock(return_value=background_body)
        background_page = mock.Mock()
        background_page.frames = [background_frame]
        current_page = mock.Mock()
        current_page.frames = [current_frame]
        current_page.context.pages = [background_page, current_page]

        reason = await agent._detect_non_earnings_event(current_page)

        self.assertIsNone(reason)
        background_frame.locator.assert_not_called()

    def test_human_event_checkpoint_accepts_earnings_registration(self):
        steps = [
            {
                "text": "Q1 2026 Earnings Call Webcast",
                "context_text": "Q1 2026 Earnings Call",
            }
        ]

        self.assertTrue(
            BrowserWebcastAgent._workflow_checkpoint_succeeded(
                "event_selection",
                HumanPageAssessment("registration"),
                steps,
            )
        )
        self.assertFalse(
            BrowserWebcastAgent._workflow_checkpoint_succeeded(
                "event_selection",
                HumanPageAssessment("registration"),
                [{"text": "Mizuho Technology Conference"}],
            )
        )

    async def test_human_event_path_is_saved_before_playback(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        agent._human_handoff_count = 1
        agent._human_actions_by_handoff[1] = [
            {
                "type": "click",
                "selector_hint": "a[aria-label='Q1 earnings webcast']",
                "text": "Q1 2026 Earnings Call Webcast",
                "aria_label": "",
                "title": "",
                "href": "https://provider.example.com/q1-earnings",
                "context_text": "Q1 2026 Earnings Call",
                "page_url": "https://investor.example.com/events",
                "frame_url": "https://investor.example.com/events",
                "captured_at": 1,
            }
        ]
        page = mock.Mock()
        page.url = "https://provider.example.com/register"

        with (
            mock.patch.object(
                agent,
                "_classify_human_page",
                new=mock.AsyncMock(return_value=HumanPageAssessment("registration")),
            ),
            mock.patch.object(
                agent,
                "_save_human_workflow",
                return_value=42,
            ) as save_workflow,
        ):
            assessment = await agent._checkpoint_human_workflow(
                stage="event_selection",
                source_url="https://investor.example.com/events",
                page=page,
            )

        self.assertEqual(assessment.state, "registration")
        pending = save_workflow.call_args.args[0]
        self.assertEqual(pending["stage"], "event_selection")
        self.assertEqual(len(pending["steps"]), 1)

    async def test_human_handoff_saves_completed_browser_session(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        page = mock.Mock()
        page.url = "https://provider.example.com/register"
        page.context.pages = [page]
        agent.human_loop_enabled = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            agent.human_resume_path = Path(temporary_directory) / "resume"
            agent.human_handoff_path = Path(temporary_directory) / "handoff.json"
            agent.human_resume_path.touch()

            with (
                mock.patch.object(
                    agent,
                    "_clear_human_action_queue",
                    new=mock.AsyncMock(),
                ),
                mock.patch.object(
                    agent,
                    "_usable_context_pages",
                    return_value=[page],
                ),
                mock.patch.object(
                    agent,
                    "_drain_human_actions",
                    new=mock.AsyncMock(),
                ),
                mock.patch.object(
                    agent,
                    "_human_return_target_page",
                    return_value=page,
                ),
                mock.patch.object(
                    agent,
                    "_checkpoint_human_workflow",
                    new=mock.AsyncMock(return_value=HumanPageAssessment("registration")),
                ),
                mock.patch.object(
                    agent,
                    "_save_storage_state",
                    new=mock.AsyncMock(),
                ) as save_storage_state,
                mock.patch.object(
                    agent,
                    "_detect_access_barrier",
                    new=mock.AsyncMock(return_value=None),
                ),
            ):
                self.assertTrue(
                    await agent._human_handoff(
                        page,
                        stage="registration",
                        reason="manual verification",
                    )
                )

        save_storage_state.assert_awaited_once_with(page.context)

    async def test_human_player_click_is_promoted_to_playback_workflow(self):
        agent = BrowserWebcastAgent(
            "CRH",
            "https://www.crh.com/investors/results-presentations/",
        )
        agent._human_handoff_count = 1
        agent._human_actions_by_handoff[1] = [
            {
                "type": "click",
                "selector_hint": "button",
                "text": "",
                "aria_label": "",
                "title": "",
                "href": "",
                "page_url": "https://events.q4inc.com/attendee/176645889",
                "frame_url": "https://events.q4inc.com/attendee/176645889",
                "captured_at": 1,
            }
        ]
        page = mock.Mock()
        page.url = "https://events.q4inc.com/attendee/176645889"

        with (
            mock.patch.object(
                agent,
                "_classify_human_page",
                new=mock.AsyncMock(return_value=HumanPageAssessment("playback")),
            ),
            mock.patch.object(
                agent,
                "_save_human_workflow",
                return_value=603,
            ) as save_workflow,
        ):
            assessment = await agent._checkpoint_human_workflow(
                stage="candidate",
                source_url="https://events.q4inc.com/attendee/176645889",
                page=page,
            )

        self.assertEqual(assessment.state, "playback")
        pending = save_workflow.call_args.args[0]
        self.assertEqual(pending["stage"], "playback")
        self.assertEqual(len(pending["steps"]), 1)

    async def test_human_player_click_is_promoted_before_media_probe_confirms_audio(self):
        agent = BrowserWebcastAgent(
            "CRH",
            "https://www.crh.com/investors/results-presentations/",
        )
        agent._human_handoff_count = 1
        agent._human_actions_by_handoff[1] = [
            {
                "type": "click",
                "selector_hint": "button",
                "text": "",
                "aria_label": "",
                "title": "",
                "href": "",
                "page_url": "https://events.q4inc.com/attendee/176645889",
                "frame_url": "https://events.q4inc.com/attendee/176645889",
                "captured_at": 1,
            }
        ]
        page = mock.Mock()
        page.url = "https://events.q4inc.com/attendee/176645889"

        with (
            mock.patch.object(
                agent,
                "_classify_human_page",
                new=mock.AsyncMock(return_value=HumanPageAssessment("player")),
            ),
            mock.patch.object(
                agent,
                "_save_human_workflow",
                return_value=604,
            ) as save_workflow,
        ):
            assessment = await agent._checkpoint_human_workflow(
                stage="candidate",
                source_url="https://events.q4inc.com/attendee/176645889",
                page=page,
            )

        self.assertEqual(assessment.state, "player")
        pending = save_workflow.call_args.args[0]
        self.assertEqual(pending["stage"], "playback")

    def test_human_return_prefers_new_tab_over_old_last_tab(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        source_page = mock.Mock()
        stale_page = mock.Mock()
        new_page = mock.Mock()
        for page, url in (
            (source_page, "https://investor.example.com/events"),
            (stale_page, "https://conference.example.com/register"),
            (new_page, "https://earnings.example.com/register"),
        ):
            page.url = url
            page.is_closed = mock.Mock(return_value=False)
        source_page.context.pages = [source_page, stale_page, new_page]

        returned = agent._human_return_target_page(
            source_page,
            {id(source_page), id(stale_page)},
        )

        self.assertIs(returned, new_page)

    def test_human_return_prefers_last_action_tab_when_no_tab_was_opened(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        source_page = mock.Mock()
        stale_page = mock.Mock()
        source_page.url = "https://investor.example.com/events?page=2"
        stale_page.url = "https://conference.example.com/register"
        source_page.is_closed = mock.Mock(return_value=False)
        stale_page.is_closed = mock.Mock(return_value=False)
        source_page.context.pages = [source_page, stale_page]
        agent._last_human_action_page = source_page

        returned = agent._human_return_target_page(
            source_page,
            {id(source_page), id(stale_page)},
        )

        self.assertIs(returned, source_page)

    async def test_replay_proxy_registration_trains_downstream_not_event_selection(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        agent.lifecycle = "replay"
        page = mock.Mock()
        page.url = "https://conference.example.com/register"

        with (
            mock.patch.object(
                agent,
                "_wait_for_dynamic_page",
                new=mock.AsyncMock(),
            ),
            mock.patch.object(
                agent,
                "accept_cookie_banners",
                new=mock.AsyncMock(),
            ),
            mock.patch.object(
                agent,
                "_detect_access_barrier",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(
                agent,
                "_detect_non_earnings_event",
                new=mock.AsyncMock(return_value="Technology Conference"),
            ),
            mock.patch.object(
                agent,
                "_detect_registration_barrier",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(
                agent,
                "has_registration_form",
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            assessment = await agent._classify_human_page(page)

        self.assertEqual(assessment.state, "registration")
        self.assertIn("training proxy", assessment.reason or "")
        self.assertFalse(
            agent._workflow_checkpoint_succeeded(
                "event_selection",
                assessment,
                [{"text": "Webcast"}],
            )
        )
        self.assertTrue(
            agent._workflow_checkpoint_succeeded(
                "registration",
                HumanPageAssessment("player", assessment.reason),
                [{"text": "Submit"}],
            )
        )

    async def test_training_proxy_is_allowed_only_for_replay_downstream_pages(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        page = mock.Mock()
        page.url = "https://conference.example.com/register"

        with (
            mock.patch.object(
                agent,
                "_detect_registration_barrier",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(
                agent,
                "has_registration_form",
                new=mock.AsyncMock(return_value=True),
            ) as has_form,
            mock.patch.object(
                agent,
                "_has_visible_media_element",
                new=mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                agent,
                "detect_active_playback",
                new=mock.AsyncMock(return_value=None),
            ),
        ):
            agent.lifecycle = "live"
            self.assertFalse(
                await agent._accept_replay_training_proxy(
                    page,
                    "Technology Conference",
                )
            )
            has_form.assert_not_awaited()

            agent.lifecycle = "replay"
            self.assertTrue(
                await agent._accept_replay_training_proxy(
                    page,
                    "Technology Conference",
                )
            )
        self.assertEqual(agent._training_proxy_event, "Technology Conference")

    async def test_training_proxy_accepts_captured_provider_media(self):
        agent = BrowserWebcastAgent(
            ticker="CRM",
            ir_url="https://investor.example.com/events",
        )
        agent.lifecycle = "replay"
        agent.media_candidates = ["https://cdn.example.com/replay/master.m3u8"]
        page = mock.Mock()
        page.url = "https://video.example.com/watch/123"

        with (
            mock.patch.object(
                agent,
                "_detect_registration_barrier",
                mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(
                agent,
                "has_registration_form",
                mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                agent,
                "_has_visible_media_element",
                mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                agent,
                "detect_active_playback",
                mock.AsyncMock(return_value=None),
            ),
        ):
            self.assertTrue(
                await agent._accept_replay_training_proxy(
                    page,
                    "Webinar",
                )
            )

        self.assertEqual(agent._training_proxy_event, "Webinar")

    async def test_registration_retry_resumes_from_latest_player_tab(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        agent.human_retry_limit = 1
        form_page = mock.Mock()
        player_page = mock.Mock()

        with (
            mock.patch.object(
                agent,
                "handle_registration_form",
                new=mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                agent,
                "_human_handoff",
                new=mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(
                agent,
                "_page_after_human_handoff",
                return_value=player_page,
            ),
            mock.patch.object(
                agent,
                "_classify_human_page",
                new=mock.AsyncMock(return_value=HumanPageAssessment("player")),
            ),
        ):
            completed, returned_page = await agent._complete_registration_with_human(
                form_page,
                TimeoutError,
            )

        self.assertTrue(completed)
        self.assertIs(returned_page, player_page)

    async def test_verified_human_workflow_replays_clicks_in_order(self):
        agent = BrowserWebcastAgent("CRM", "https://investor.example.com/events")
        page = mock.Mock()
        page.url = "https://investor.example.com/events"
        page.is_closed = mock.Mock(return_value=False)
        page.context.pages = [page]
        first = mock.Mock()
        first.click = mock.AsyncMock()
        second = mock.Mock()
        second.click = mock.AsyncMock()
        recipe = WebcastRecipe(
            recipe_id=9,
            domain="investor.example.com",
            selectors=("0:a", "1:a"),
            frame_hostname=None,
            target_text="Q1 earnings webcast",
            target_href_path="/q1",
            strategy="human_workflow",
            lifecycle="replay",
            confidence=0.9,
            stage="event_selection",
            evidence={
                "workflow_stage": "event_selection",
                "steps": [
                    {"type": "click", "text": "2"},
                    {
                        "type": "click",
                        "text": "Q1 2026 Earnings Call Webcast",
                        "context_text": "Q1 2026 Earnings Call",
                    },
                ],
            },
        )

        with (
            mock.patch.object(
                agent,
                "_load_verified_human_workflows",
                return_value=[recipe],
            ),
            mock.patch.object(
                agent,
                "_find_human_workflow_step",
                new=mock.AsyncMock(side_effect=[first, second]),
            ),
            mock.patch.object(
                agent,
                "_wait_for_clicked_target",
                new=mock.AsyncMock(return_value=page),
            ),
            mock.patch.object(agent, "_wait_for_dynamic_page", new=mock.AsyncMock()),
            mock.patch.object(
                agent,
                "_classify_human_page",
                new=mock.AsyncMock(return_value=HumanPageAssessment("registration")),
            ),
            mock.patch(
                "data_pipeline.database.record_webcast_recipe_outcome",
            ) as record_outcome,
        ):
            returned_page, applied = await agent._apply_human_workflow(
                page,
                stage="event_selection",
            )

        self.assertTrue(applied)
        self.assertIs(returned_page, page)
        first.click.assert_awaited_once()
        second.click.assert_awaited_once()
        record_outcome.assert_called_once_with(9, success=True)


if __name__ == "__main__":
    unittest.main()
