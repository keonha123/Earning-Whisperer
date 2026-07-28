import asyncio
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from data_pipeline.collectors.streams.browser_webcast import (
    ACCESS_BARRIER_PATTERN,
    ALREADY_REGISTERED_PATTERN,
    BrowserWebcastAgent,
    DYNAMIC_LOADING_PATTERN,
    EXPIRED_EVENT_PATTERN,
    HTTP_ACCESS_BARRIER_STATUSES,
    NOT_LIVE_EVENT_PATTERN,
    RESOURCE_NOT_FOUND_PATTERN,
    InvestorProfile,
    PLAY_TEXT_PATTERN,
    REGISTRATION_EMAIL_ERROR_PATTERN,
    REGISTRATION_BARRIER_PATTERN,
    REGISTRATION_FORM_TEXT_PATTERN,
    archive_navigation_url,
    default_chromium_executable,
    is_direct_player_url,
    is_audio_priming_player_url,
    MISSING_RESOURCE_URL_PATTERN,
    NON_PLAYBACK_DOCUMENT_PATTERN,
    future_event_date_reason,
    is_media_candidate_url,
    is_nonessential_popup_url,
    is_playback_control_label,
    provider_archive_navigation_url,
    REPLAY_EXPANSION_LABEL_PATTERN,
)
from data_pipeline.collectors.streams.webcast_learning import WebcastCandidate


class BrowserWebcastHelpersTest(unittest.TestCase):
    def test_media_candidate_detection(self):
        self.assertTrue(is_media_candidate_url("https://example.com/audio/playlist.m3u8"))
        self.assertTrue(is_media_candidate_url("https://example.com/video.mp4?token=abc"))
        self.assertFalse(is_media_candidate_url("https://example.com/investor/events"))
        self.assertFalse(
            is_media_candidate_url(
                "https://browser.events.data.microsoft.com/OneCollector/1.0/?content-type=application/x-json-stream"
            )
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
        self.assertEqual(profile.industry_affiliation, "Other")
        self.assertEqual(profile.country, "United States")
        self.assertEqual(profile.occupation, "Other")

    def test_investor_profile_keeps_q4_credentials_separate(self):
        with mock.patch.dict(
            "os.environ",
            {
                "WEBCAST_EMAIL": "generic@example.com",
                "WEBCAST_PASSWORD": "generic-secret",
                "WEBCAST_FIRST_NAME": "Generic",
                "WEBCAST_LAST_NAME": "Investor",
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
        self.assertEqual(profile.q4_email, "q4@example.com")
        self.assertEqual(profile.q4_password, "q4-secret")
        self.assertEqual(profile.q4_first_name, "Q4")
        self.assertEqual(profile.q4_last_name, "Attendee")

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
        self.assertIsNotNone(
            ALREADY_REGISTERED_PATTERN.search("You will receive an email containing login instructions.")
        )

    def test_registration_email_error_pattern_matches_provider_validation(self):
        self.assertIsNotNone(
            REGISTRATION_EMAIL_ERROR_PATTERN.search(
                "Please enter a valid email address. (Error 1022-228581076)"
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

    def test_expired_event_pattern_separates_retired_recordings(self):
        self.assertIsNotNone(
            EXPIRED_EVENT_PATTERN.search(
                "The recording of this session is not available any more."
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

    def test_resource_not_found_pattern_separates_dead_provider_urls(self):
        self.assertIsNotNone(
            RESOURCE_NOT_FOUND_PATTERN.search(
                "The resource you have requested cannot be found."
            )
        )

    def test_play_text_pattern_does_not_match_overview(self):
        self.assertIsNone(PLAY_TEXT_PATTERN.search("Overview"))
        self.assertIsNotNone(PLAY_TEXT_PATTERN.search("Play webcast"))

    def test_playback_control_label_rejects_navigation_and_downloads(self):
        for label in (
            "Join Our Team",
            "JOIN US",
            "Overview",
            "Download Audio Replay (MP3)",
            "To listen to the webcast, please register here",
            "Shop Watch",
            "Webcast",
        ):
            with self.subTest(label=label):
                self.assertFalse(is_playback_control_label(label))

    def test_playback_control_label_keeps_explicit_player_actions(self):
        for label in (
            "Listen to the Webcast",
            "Watch the Replay",
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
        self.assertFalse(is_direct_player_url("https://investor.example.com/events"))

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

    def test_registration_submission_is_disabled_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            agent = BrowserWebcastAgent("MSFT", "https://investor.example.com/events")

        self.assertFalse(agent.allow_registration_submission)

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


class BrowserPlaybackDetectionTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_detects_visible_pause_control_as_active_playback(self):
        agent = BrowserWebcastAgent("ISRG", "https://example.com/webcast")
        frame = mock.Mock()
        frame.evaluate = mock.AsyncMock(return_value="visible pause control")
        page = mock.Mock()
        page.frames = [frame]

        reason = await agent.detect_active_playback(page)

        self.assertEqual(reason, "visible pause control")

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
        frame.locator = mock.Mock(return_value=controls)
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


if __name__ == "__main__":
    unittest.main()
