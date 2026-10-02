import unittest

from data_pipeline.tools.debug.visible_webcast import (
    clean_logs,
    classify_phase,
    parse_args,
    stage_values,
    visible_events,
)


class VisibleWebcastTest(unittest.TestCase):
    def test_manual_confirmation_phase(self):
        phase = classify_phase(
            "NOVNC_READY\nMANUAL_BROWSER_READY signal_file=/tmp/ready",
            running=True,
            exit_code=None,
        )

        self.assertEqual(phase.key, "manual")
        stages = stage_values(phase)
        self.assertEqual(stages[0]["status"], "complete")
        self.assertEqual(stages[2]["status"], "active")

    def test_audio_success_is_terminal_success(self):
        phase = classify_phase(
            "PLAYBACK_READY_CONFIRMED\nAUDIO_DETECTED max_volume=-18.0dB",
            running=False,
            exit_code=0,
        )

        self.assertEqual(phase.key, "success")
        self.assertTrue(all(stage["status"] == "complete" for stage in stage_values(phase)))

    def test_failed_audio_is_reported_at_audio_stage(self):
        phase = classify_phase(
            "PLAYBACK_READY_CONFIRMED\nAUDIO_NOT_DETECTED within=35s",
            running=False,
            exit_code=1,
        )

        self.assertEqual(phase.key, "failed")
        self.assertEqual(phase.index, 6)

    def test_registration_required_is_reported_as_player_failure(self):
        phase = classify_phase(
            "[UNH] REGISTRATION_REQUIRED registration submission is disabled",
            running=True,
            exit_code=None,
        )

        self.assertEqual(phase.key, "failed")
        self.assertEqual(phase.index, 4)

    def test_visible_events_filters_noise(self):
        events = visible_events(
            "xkb warning\n"
            "[MSFT] opening IR page: https://example.com\n"
            "[MSFT] clicking webcast candidate: Listen\n"
        )

        self.assertEqual(len(events), 2)

    def test_clean_logs_hides_display_noise(self):
        cleaned = clean_logs(
            "The XKEYBOARD keymap compiler (xkbcomp) reports:\n"
            "> Warning: Could not resolve keysym XF86CameraAccessEnable\n"
            "NOVNC_READY url=http://127.0.0.1:6080/vnc.html\n"
        )

        self.assertEqual(cleaned, "NOVNC_READY url=http://127.0.0.1:6080/vnc.html")

    def test_automatic_discovery_and_registration_are_explicit(self):
        defaults = parse_args(
            ["--ticker", "UNH", "--url", "https://example.com/investors"]
        )
        automatic = parse_args(
            [
                "--ticker",
                "UNH",
                "--url",
                "https://example.com/investors",
                "--auto-start",
                "--allow-registration-submission",
            ]
        )

        self.assertFalse(defaults.auto_start)
        self.assertFalse(defaults.allow_registration_submission)
        self.assertEqual(defaults.success_hold, 60)
        self.assertTrue(automatic.auto_start)
        self.assertTrue(automatic.allow_registration_submission)


if __name__ == "__main__":
    unittest.main()
