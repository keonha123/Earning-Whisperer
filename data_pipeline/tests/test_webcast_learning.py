import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from data_pipeline.collectors.streams.recipe_outcome import record_context_outcome
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate,
    WebcastRecipe,
    candidate_event_date,
    choose_heuristic_candidate,
    extract_response_text,
    generalized_candidate_bonus,
    make_generalized_patterns,
    make_recipe,
    parse_vision_selection,
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

    def test_heuristic_rejects_calendar_and_footer_links(self):
        calendar = candidate(text="Add event to calendar", href_path="/calendar")
        footer = candidate(
            text="Webcasting Platform Powered by ACCESS Newswire Copyright 2026",
            href_path="/products/investor-relations/earnings-calls",
        )

        self.assertIsNone(choose_heuristic_candidate([calendar, footer]))

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
