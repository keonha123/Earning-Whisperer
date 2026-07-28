import unittest
from datetime import datetime, timezone

from data_pipeline.database import prioritize_webcast_learning_targets
from data_pipeline.tools.learning.webcast_learning_batch import (
    capture_environment,
    classify_probe_outcome,
    diagnose_probe_error,
    is_future_event,
    parse_args,
)


class UniverseLearningBatchTest(unittest.TestCase):
    def test_classifies_audio_and_access_results(self):
        self.assertEqual(classify_probe_outcome(True, None), "audible")
        self.assertEqual(classify_probe_outcome(False, "page access blocked: Access Denied"), "blocked")
        self.assertEqual(
            classify_probe_outcome(False, "AUTH_REQUIRED WEBCAST_PASSWORD/Q4_PASSWORD is missing"),
            "auth_required",
        )
        self.assertEqual(classify_probe_outcome(False, "webcast button not found"), "no_candidate")
        self.assertEqual(classify_probe_outcome(False, "AUDIO_NOT_DETECTED within=15s"), "no_audio")
        self.assertEqual(
            classify_probe_outcome(False, "Failure: Module initialization failed"),
            "capture_runtime_failed",
        )
        self.assertEqual(
            classify_probe_outcome(
                False,
                "W: [pulseaudio] main.c: Daemon startup failed.",
            ),
            "capture_runtime_failed",
        )
        self.assertEqual(
            classify_probe_outcome(
                False,
                "EXPIRED_EVENT The recording of this session is not available",
            ),
            "expired",
        )
        self.assertEqual(
            classify_probe_outcome(
                False,
                "NOT_LIVE_YET Entry to the live presentation is not yet available",
            ),
            "not_live_yet",
        )
        self.assertEqual(
            classify_probe_outcome(
                False,
                "RESOURCE_NOT_FOUND The resource you have requested cannot be found",
            ),
            "not_found",
        )

    def test_diagnoses_wrapped_probe_errors(self):
        self.assertEqual(
            diagnose_probe_error(
                "audio probe failed: no active media or playable control found"
            ),
            "player_control_missing",
        )
        self.assertEqual(
            diagnose_probe_error(
                "registration form remained visible invalid_fields=0"
            ),
            "registration_failed",
        )
        self.assertEqual(
            diagnose_probe_error(
                "REGISTRATION_BLOCKED anti-bot captcha requires manual verification"
            ),
            "blocked",
        )
        self.assertEqual(
            diagnose_probe_error(
                "webcast opened but playback was not detected | WEBCAST_EXITED_BEFORE_PLAYBACK_READY"
            ),
            "playback_activation_failed",
        )
        self.assertEqual(
            diagnose_probe_error(
                "no active media or playable control found | "
                "WEBCAST_EXITED_BEFORE_PLAYBACK_READY"
            ),
            "playback_activation_failed",
        )
        self.assertEqual(
            diagnose_probe_error("audio probe failed: WAITING_FOR_PLAYBACK_READY timeout=45s"),
            "playback_ready_timeout",
        )
        self.assertEqual(
            diagnose_probe_error("replay probe terminated after browser process timeout"),
            "probe_interrupted",
        )
        self.assertEqual(
            diagnose_probe_error("audio probe failed: Failure: Module initialization failed"),
            "capture_runtime_failed",
        )
        self.assertEqual(
            diagnose_probe_error(
                "audio probe failed: W: [pulseaudio] main.c: Daemon startup failed."
            ),
            "capture_runtime_failed",
        )

    def test_capture_environment_keeps_browser_alive_for_audio_probe(self):
        args = parse_args(["--audio-wait-seconds", "20", "--warmup-seconds", "4"])
        environment = capture_environment(args)

        self.assertEqual(environment["WEBCAST_HEADED"], "true")
        self.assertEqual(environment["WEBCAST_VNC_ENABLED"], "false")
        self.assertEqual(environment["WEBCAST_GENERALIZED_LEARNING_ENABLED"], "true")
        self.assertEqual(environment["WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS"], "90")
        self.assertEqual(environment["DATE_STREAM_AUDIO_WAIT_SECONDS"], "20")
        self.assertEqual(environment["WEBCAST_HOLD_SECONDS"], "39")

    def test_capture_environment_can_disable_generalized_learning(self):
        args = parse_args(["--disable-generalized-learning"])
        self.assertEqual(
            capture_environment(args)["WEBCAST_GENERALIZED_LEARNING_ENABLED"],
            "false",
        )

    def test_prioritizes_explicit_webcast_and_event_urls(self):
        targets = [
            {"ticker": "IR", "target_kind": "ir_url"},
            {"ticker": "EVENT", "target_kind": "event_url"},
            {"ticker": "WEBCAST", "target_kind": "webcast_url"},
        ]

        ordered = prioritize_webcast_learning_targets(targets)

        self.assertEqual([target["ticker"] for target in ordered], ["WEBCAST", "EVENT", "IR"])

    def test_future_event_is_discovered_without_audio_probe(self):
        self.assertTrue(
            is_future_event({"scheduled_at_utc": datetime(2099, 1, 1, tzinfo=timezone.utc)})
        )
        self.assertFalse(
            is_future_event({"scheduled_at_utc": datetime(2000, 1, 1, tzinfo=timezone.utc)})
        )


if __name__ == "__main__":
    unittest.main()
