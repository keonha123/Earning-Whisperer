import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data_pipeline.tools.debug.visible_webcast import (
    VisibleWebcastRun,
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

    def test_human_handoff_phase_waits_for_baton_return(self):
        waiting = classify_phase(
            "HUMAN_HANDOFF stage=candidate reason=missing\n",
            running=True,
            exit_code=None,
        )
        returned = classify_phase(
            "HUMAN_HANDOFF stage=candidate\nHUMAN_BATON_RETURNED stage=candidate\n",
            running=True,
            exit_code=None,
        )

        self.assertEqual(waiting.key, "manual")
        self.assertNotEqual(returned.key, "manual")
        timed_out = classify_phase(
            "HUMAN_HANDOFF_TIMEOUT stage=audio timeout=30s",
            running=False,
            exit_code=1,
        )
        self.assertEqual(timed_out.key, "failed")

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
            "[MSFT] REPLAY_TRAINING_PROXY event=Technology Conference\n"
            "[MSFT] clicking webcast candidate: Listen\n"
        )

        self.assertEqual(len(events), 3)

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
        self.assertFalse(defaults.human_loop)
        self.assertFalse(defaults.allow_registration_submission)
        self.assertEqual(defaults.success_hold, 60)
        self.assertTrue(automatic.auto_start)
        self.assertTrue(automatic.allow_registration_submission)
        self.assertFalse(automatic.fresh_browser)

        collaborative = parse_args(
            ["--ticker", "UNH", "--url", "https://example.com/investors", "--human-loop"]
        )
        self.assertTrue(collaborative.human_loop)

    def test_auto_start_does_not_inject_initial_manual_gate(self):
        args = parse_args(
            [
                "--ticker",
                "MSFT",
                "--url",
                "https://example.com/investors",
                "--auto-start",
                "--skip-db",
            ]
        )
        captured: list[list[str]] = []

        def fake_run(command: list[str]):
            captured.append(command)
            return mock.Mock(returncode=0, stdout="")

        with mock.patch(
            "data_pipeline.tools.debug.visible_webcast._run_output",
            side_effect=fake_run,
        ):
            VisibleWebcastRun(args).start()

        self.assertEqual(len(captured), 1)
        command = captured[0]
        self.assertNotIn("WEBCAST_MANUAL_READY_FILE=/tmp/ew-visible-webcast-ready", command)

    def test_human_loop_keeps_initial_manual_gate(self):
        args = parse_args(
            [
                "--ticker",
                "MSFT",
                "--url",
                "https://example.com/investors",
                "--auto-start",
                "--human-loop",
                "--skip-db",
            ]
        )
        captured: list[list[str]] = []

        def fake_run(command: list[str]):
            captured.append(command)
            return mock.Mock(returncode=0, stdout="")

        with mock.patch(
            "data_pipeline.tools.debug.visible_webcast._run_output",
            side_effect=fake_run,
        ):
            VisibleWebcastRun(args).start()

        self.assertEqual(len(captured), 1)
        command = captured[0]
        self.assertIn("WEBCAST_MANUAL_READY_FILE=/tmp/ew-visible-webcast-ready", command)

    def test_fresh_browser_uses_a_run_specific_storage_state(self):
        args = parse_args(
            [
                "--ticker",
                "AEE",
                "--url",
                "https://example.com/investors",
                "--auto-start",
                "--fresh-browser",
                "--skip-db",
            ]
        )
        captured: list[list[str]] = []

        def fake_run(command: list[str]):
            captured.append(command)
            return mock.Mock(returncode=0, stdout="")

        with mock.patch(
            "data_pipeline.tools.debug.visible_webcast._run_output",
            side_effect=fake_run,
        ):
            visible_run = VisibleWebcastRun(args)
            visible_run.start()

        command = captured[0]
        storage_env = next(
            value for value in command if value.startswith("WEBCAST_STORAGE_STATE=")
        )
        self.assertNotEqual(
            storage_env,
            "WEBCAST_STORAGE_STATE=/app/data_pipeline/.runtime/state/q4_auth.json",
        )
        self.assertIn("-fresh.json", storage_env)

    def test_visible_run_migrates_legacy_storage_to_writable_runtime_path(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            repo_root = Path(temporary_dir)
            legacy_path = repo_root / "data_pipeline" / ".state" / "q4_auth.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text('{"cookies": []}', encoding="utf-8")
            args = parse_args(
                ["--ticker", "CRM", "--url", "https://example.com/investors"]
            )

            with mock.patch(
                "data_pipeline.tools.debug.visible_webcast.REPO_ROOT",
                repo_root,
            ):
                visible_run = VisibleWebcastRun(args)

            self.assertEqual(
                visible_run.storage_state_path,
                repo_root / "data_pipeline" / ".runtime" / "state" / "q4_auth.json",
            )
            self.assertEqual(
                visible_run.storage_state_path.read_text(encoding="utf-8"),
                '{"cookies": []}',
            )


if __name__ == "__main__":
    unittest.main()
