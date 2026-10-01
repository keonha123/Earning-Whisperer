import json
import unittest

from data_pipeline import database
from data_pipeline.stt_worker.manager import WebcastProbeResult
from data_pipeline.tools.replay import training_surface_audit as audit
from data_pipeline.tools.replay.training_surface_audit import (
    CandidateProbeAttempt,
    build_training_surface_batch_plan,
    build_training_surface_review_queues,
    choose_preferred_probe_attempt,
    classify_training_surface_review_queue,
    classify_training_surface_outcome,
    effective_probe_timeout_seconds,
    extract_registration_preview,
    infer_surface_kind,
    is_non_media_url,
    parse_args,
    prior_event_detail_url,
    reported_surface_url,
    should_stop_candidate_probe,
    should_try_internal_ir_crawl,
)


class TrainingSurfaceAuditTest(unittest.TestCase):
    def test_prefers_downstream_provider_failure_over_later_ir_navigation_failure(self):
        provider_result = WebcastProbeResult(
            audible=False,
            error="player did not become active",
            output="webcast target opened: https://provider.example.com/player",
            return_code=1,
        )
        issuer_result = WebcastProbeResult(
            audible=False,
            error="navigation timed out",
            output="opening IR page: https://investor.example.com/events",
            return_code=1,
        )

        selected = choose_preferred_probe_attempt(
            [
                CandidateProbeAttempt(
                    result=provider_result,
                    selected_url="https://provider.example.com/player",
                    status="playback_failed",
                    surface_kind="webcast",
                ),
                CandidateProbeAttempt(
                    result=issuer_result,
                    selected_url="https://investor.example.com/events",
                    status="navigation_failed",
                    surface_kind="unknown",
                ),
            ]
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.result, provider_result)
        self.assertEqual(selected.selected_url, "https://provider.example.com/player")

    def test_prefers_audible_candidate(self):
        audible_result = WebcastProbeResult(
            audible=True,
            error=None,
            output="AUDIO_DETECTED max_volume=-12.0dB",
            return_code=0,
        )
        selected = choose_preferred_probe_attempt(
            [
                CandidateProbeAttempt(
                    result=WebcastProbeResult(
                        audible=False,
                        error="registration form handling failed",
                        output="registration form detected",
                        return_code=1,
                    ),
                    selected_url="https://provider.example.com/register",
                    status="registration_failed",
                    surface_kind="webcast",
                ),
                CandidateProbeAttempt(
                    result=audible_result,
                    selected_url="https://provider.example.com/player",
                    status="audible",
                    surface_kind="webcast",
                ),
            ]
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.result, audible_result)

    def test_probe_timeout_covers_media_fallback_audio_window(self):
        args = parse_args(
            [
                "--playback-timeout-seconds",
                "45",
                "--warmup-seconds",
                "3",
                "--audio-wait-seconds",
                "45",
                "--timeout-seconds",
                "125",
            ]
        )

        self.assertEqual(effective_probe_timeout_seconds(args), 168)

    def test_audio_not_detected_is_not_misclassified_as_player_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed",
            output=(
                "PLAYBACK_READY_CONFIRMED\n"
                "AUDIO_NOT_DETECTED within=45s threshold=-55.0dB"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://media.example.com/replay.mp4",
                ir_url="https://investor.example.com/events",
            ),
            "no_audio",
        )

    def test_internal_crawl_retries_navigation_failure(self):
        self.assertTrue(should_try_internal_ir_crawl("navigation_failed"))
        self.assertTrue(should_try_internal_ir_crawl("candidate_discovery_retry"))
        self.assertFalse(should_try_internal_ir_crawl("playback_failed"))

    def test_navigation_failure_reuses_same_issuer_event_detail_for_static_crawl(self):
        self.assertEqual(
            prior_event_detail_url(
                {
                    "status": "navigation_failed",
                    "ir_url": "https://investor.example.com/news-releases",
                    "selected_url": (
                        "https://investor.example.com/events/event-details/q2-2026"
                    ),
                }
            ),
            "https://investor.example.com/events/event-details/q2-2026",
        )

    def test_prior_event_detail_does_not_fetch_an_external_or_unrelated_url(self):
        self.assertIsNone(
            prior_event_detail_url(
                {
                    "status": "navigation_failed",
                    "ir_url": "https://investor.example.com/news-releases",
                    "selected_url": "https://provider.example.com/player",
                }
            )
        )

    def test_reported_surface_url_recovers_direct_target_from_output(self):
        self.assertEqual(
            reported_surface_url(
                "opening candidate href directly: "
                "https://provider.example.com/event-details/q2-2026\n"
                "PLAYBACK_READY_TIMED_OUT",
                ir_url="https://investor.example.com/events",
            ),
            "https://provider.example.com/event-details/q2-2026",
        )

    def test_reported_surface_url_does_not_return_original_ir_page(self):
        self.assertIsNone(
            reported_surface_url(
                "webcast target opened: https://investor.example.com/events",
                ir_url="https://investor.example.com/events",
            )
        )

    def test_audible_target_is_audio_proven(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {"status": "audible", "surface_kind": "webcast"}
            ),
            "audio_proven",
        )

    def test_prior_audio_proof_is_not_demoted_by_transient_failure(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "navigation_failed",
                    "audible_count": 1,
                    "last_output": "previously recorded AUDIO_DETECTED",
                }
            ),
            "audio_proven",
        )

    def test_registration_gate_stops_unsubmitted_candidate_fanout(self):
        self.assertTrue(
            should_stop_candidate_probe(
                "registration_required",
                audible=False,
                allow_registration_submission=False,
            )
        )
        self.assertTrue(
            should_stop_candidate_probe(
                "auth_required",
                audible=False,
                allow_registration_submission=False,
            )
        )
        self.assertTrue(
            should_stop_candidate_probe(
                "registration_preview",
                audible=False,
                allow_registration_submission=False,
            )
        )
        self.assertFalse(
            should_stop_candidate_probe(
                "playback_failed",
                audible=False,
                allow_registration_submission=False,
            )
        )
        self.assertFalse(
            should_stop_candidate_probe(
                "registration_required",
                audible=False,
                allow_registration_submission=True,
            )
        )

    def test_candidate_playback_failure_goes_to_human_downstream(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "playback_failed",
                    "surface_kind": "webcast",
                    "selected_url": "https://provider.example.com/player",
                }
            ),
            "human_downstream",
        )

    def test_archive_fallback_without_candidate_is_automatically_retried(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "playback_failed",
                    "surface_kind": "webcast",
                    "ir_url": "https://stock.example.com/",
                    "selected_url": "https://stock.example.com/news-events",
                    "last_output": (
                        "no playback control; opening archive fallback: "
                        "https://stock.example.com/news-events\n"
                        "error=webcast button not found"
                    ),
                }
            ),
            "automatic_retry",
        )

    def test_no_candidate_is_a_retryable_discovery_state(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "no_training_surface",
                    "surface_kind": "none",
                    "ir_url": "https://investor.example.com/events",
                    "last_output": "webcast button not found",
                }
            ),
            "automatic_retry",
        )

    def test_missing_ir_url_is_entrypoint_configuration_review(self):
        result = WebcastProbeResult(
            audible=False,
            error="missing IR URL",
            output="",
            return_code=None,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url=None,
            ),
            "entrypoint_missing",
        )
        self.assertEqual(
            classify_training_surface_review_queue(
                {"status": "entrypoint_missing"}
            ),
            "entrypoint_review",
        )

    def test_blocked_entrypoint_without_candidate_requires_entrypoint_review(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "blocked",
                    "surface_kind": "unknown",
                    "ir_url": "https://investor.example.com/events",
                    "last_output": "page access blocked: Access Denied",
                }
            ),
            "entrypoint_review",
        )

    def test_candidate_found_before_navigation_failure_is_downstream_review(self):
        self.assertEqual(
            classify_training_surface_review_queue(
                {
                    "status": "navigation_failed",
                    "surface_kind": "webcast",
                    "selected_url": "https://provider.example.com/player",
                }
            ),
            "human_downstream",
        )

    def test_review_queue_report_keeps_every_ticker_once(self):
        report = build_training_surface_review_queues(
            [
                {"ticker": "AAA", "status": "audible"},
                {
                    "ticker": "BBB",
                    "status": "playback_failed",
                    "selected_url": "https://provider.example.com/player",
                    "ir_url": "https://investor.example.com/events",
                },
                {"ticker": "CCC", "status": "no_training_surface"},
                {"ticker": "DDD", "status": "blocked"},
                {"ticker": "EEE", "status": "error"},
            ]
        )
        self.assertEqual(report["total_tickers"], 5)
        self.assertEqual(sum(report["counts"].values()), 5)
        self.assertEqual(report["counts"]["human_downstream"], 1)
        self.assertEqual(report["counts"]["automatic_retry"], 2)
        self.assertEqual(report["counts"]["entrypoint_review"], 1)

    def test_batch_plan_balances_503_tickers_without_a_tiny_tail(self):
        queue_counts = {
            "audio_proven": 190,
            "human_downstream": 173,
            "entrypoint_review": 66,
            "automatic_retry": 74,
        }
        queues = {}
        sequence = 0
        for queue, count in queue_counts.items():
            items = []
            for _ in range(count):
                sequence += 1
                items.append(
                    {
                        "ticker": f"T{sequence:03d}",
                        "queue": queue,
                        "reason": "audio_detected" if queue == "audio_proven" else queue,
                        "ir_url": f"https://investor{sequence % 17}.example.com/events",
                        "selected_url": None,
                    }
                )
            queues[queue] = items
        plan = build_training_surface_batch_plan(
            {
                "total_tickers": 503,
                "counts": queue_counts,
                "queues": queues,
            },
            batch_size=50,
        )

        self.assertEqual(plan["batch_count"], 10)
        self.assertEqual(sorted(batch["size"] for batch in plan["batches"]), [50] * 7 + [51] * 3)
        tickers = [
            ticker
            for batch in plan["batches"]
            for ticker in batch["tickers"]
        ]
        self.assertEqual(len(tickers), 503)
        self.assertEqual(len(set(tickers)), 503)
        for batch in plan["batches"]:
            self.assertGreaterEqual(batch["queue_counts"]["audio_proven"], 1)
            self.assertGreaterEqual(batch["queue_counts"]["human_downstream"], 1)
            self.assertLessEqual(len(batch["preflight_tickers"]), 2)

    def test_batch_plan_arguments_are_parsed(self):
        args = parse_args(
            [
                "--plan-batches",
                "--batch-size",
                "50",
                "--batch-plan",
                "plan.json",
                "--batch-index",
                "1",
            ]
        )
        self.assertTrue(args.plan_batches)
        self.assertEqual(args.batch_size, 50)
        self.assertEqual(args.batch_plan, "plan.json")
        self.assertEqual(args.batch_index, 1)

    def test_proxy_audio_is_kept_separate_from_earnings_selection(self):
        result = WebcastProbeResult(
            audible=True,
            error=None,
            output=(
                "[CRM] REPLAY_TRAINING_PROXY event=Technology Conference\n"
                "AUDIO_DETECTED max_volume=-9.0dB"
            ),
            return_code=0,
        )

        status = classify_training_surface_outcome(
            result,
            selected_url="https://provider.example.com/player",
            ir_url="https://investor.example.com/events",
        )

        self.assertEqual(status, "audible")
        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url="https://provider.example.com/player",
                ir_url="https://investor.example.com/events",
                status=status,
            ),
            "proxy",
        )

    def test_earnings_candidate_is_identified_from_clicked_event_context(self):
        result = WebcastProbeResult(
            audible=True,
            error=None,
            output=(
                "[ABC] clicking webcast candidate: Webcast\n"
                "Q2 2026 Earnings Conference Call\n"
                "[ABC] click target stabilized: https://provider.example.com/player\n"
            ),
            return_code=0,
        )

        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url="https://provider.example.com/player",
                ir_url="https://investor.example.com/events",
                status="audible",
            ),
            "earnings",
        )

    def test_no_candidate_on_original_ir_page_is_no_training_surface(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1): webcast button not found",
            output=(
                "WAITING_FOR_PLAYBACK_READY timeout=90s\n"
                "webcast button not found\n"
                "WEBCAST_EXITED_BEFORE_PLAYBACK_READY\n"
            ),
            return_code=1,
        )

        status = classify_training_surface_outcome(
            result,
            selected_url=None,
            ir_url="https://investor.example.com/events",
        )
        self.assertEqual(status, "candidate_discovery_retry")
        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
                status=status,
            ),
            "none",
        )

    def test_archive_timeout_is_navigation_failure_not_candidate_exhaustion(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1): PLAYBACK_READY_TIMED_OUT",
            output=(
                "[PSKY] opening replay archive view: EVENTS & PRESENTATIONS\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url="https://ir.example.com/",
            ),
            "candidate_discovery_retry",
        )

    def test_opened_surface_without_player_is_playback_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error=(
                "audio probe failed (exit=1): "
                "no active media or playable control found"
            ),
            output="no active media or playable control found",
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://provider.example.com/event",
                ir_url="https://investor.example.com/events",
            ),
            "playback_failed",
        )

    def test_metameetings_public_signin_is_auth_required(self):
        result = WebcastProbeResult(
            audible=False,
            error="webcast opened but playback was not detected",
            output=(
                "webcast target opened: "
                "https://jpmorgan.metameetings.net/events/auto26/"
                "sessions/319512-aptiv/webcast/public/signin\n"
                "checking webcast registration"
            ),
            return_code=1,
        )
        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=(
                    "https://jpmorgan.metameetings.net/events/auto26/"
                    "sessions/319512-aptiv/webcast/public/signin"
                ),
                ir_url="https://investor.example.com/events",
            ),
            "auth_required",
        )

    def test_old_news_article_without_replay_surface_is_no_training_surface(self):
        result = WebcastProbeResult(
            audible=False,
            error=(
                "audio probe failed (exit=1): "
                "no active media or playable control found"
            ),
            output=(
                "webcast target opened: "
                "https://investor.example.com/news/2026/05/21/earnings-release\n"
                "no visible registration controls after 15s\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://investor.example.com/news/2026/05/21/earnings-release",
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )

    def test_not_live_takes_precedence_over_player_symptoms(self):
        result = WebcastProbeResult(
            audible=False,
            error="NOT_LIVE_YET return to this page a few minutes before the start",
            output="no active media or playable control found",
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://event.choruscall.com/mediaframe/webcast.html?webcastid=abc",
                ir_url="https://investor.example.com/events",
            ),
            "not_live_yet",
        )

    def test_not_live_in_saved_output_takes_precedence_over_player_symptoms(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed: no active media or playable control found",
            output=(
                "scheduled event date is in the future; return to this page a few "
                "minutes before the start\n"
                "no active media or playable control found\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://event.example.com/webcast",
                ir_url="https://investor.example.com/events",
            ),
            "not_live_yet",
        )

    def test_ir_event_detail_timeout_is_candidate_discovery_retry(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed: PLAYBACK_READY_TIMED_OUT",
            output=(
                "click target stabilized: "
                "https://investor.example.com/events/event-details/q2-2026\n"
                "opening candidate href directly\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://investor.example.com/events/event-details/q2-2026",
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )

    def test_blank_direct_replay_target_is_navigation_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe timed out after 90s",
            output=(
                "opening direct replay candidate: "
                "https://investor.example.com/events/event-details/q2-2026\n"
                "direct replay candidate navigation warning (attempt 2/2)\n"
                "webcast target opened: about:blank\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://investor.example.com/events/event-details/q2-2026",
                ir_url="https://investor.example.com/events",
            ),
            "navigation_failed",
        )

    def test_download_or_blank_target_is_candidate_discovery_retry(self):
        result = WebcastProbeResult(
            audible=False,
            error="download_response",
            output="download is starting; active page is about:blank",
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://investor.example.com/events/q2-results.pdf",
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )

    def test_document_cdn_link_is_not_a_downstream_surface(self):
        result = WebcastProbeResult(
            audible=False,
            error="no active media or playable control found",
            output=(
                "opening direct replay candidate: "
                "https://download.example.com/remarks.pdf?Signature=secret\n"
                "audio probe timed out\n"
            ),
            return_code=1,
        )

        self.assertTrue(is_non_media_url(result.output.split(": ", 1)[-1].split("\n", 1)[0]))
        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://download.example.com/remarks.pdf?Signature=secret",
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )
        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )

    def test_media_file_is_not_filtered_as_a_document(self):
        self.assertFalse(is_non_media_url("https://cdn.example.com/replay.mp4"))
        self.assertFalse(is_non_media_url("https://cdn.example.com/replay.m3u8"))

    def test_metameetings_sign_in_redirect_is_auth_required(self):
        result = WebcastProbeResult(
            audible=False,
            error="no active media or playable control found",
            output=(
                "webcast target opened: https://jpmorgan.metameetings.net/events/tmc26/general_signin\n"
                "Sign In\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://jpmorgan.metameetings.net/events/tmc26/sessions/318876-flex-ltd/webcast/public",
                ir_url="https://investors.example.com/events",
            ),
            "auth_required",
        )

    def test_security_verification_in_browser_output_is_blocked(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1)",
            output="registered player page is access blocked: Performing security verification",
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://provider.example.com/player",
                ir_url="https://investor.example.com/events",
            ),
            "blocked",
        )

    def test_metameetings_sign_in_in_output_is_auth_required_without_selected_url(self):
        result = WebcastProbeResult(
            audible=False,
            error="webcast opened but playback was not detected",
            output=(
                "embedded webcast target opened: "
                "https://jpmorgan.metameetings.net/events/healthcare26/general_signin"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url="https://ir.example.com/events",
            ),
            "auth_required",
        )

    def test_same_page_candidate_without_player_is_playback_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error=(
                "audio probe failed (exit=1): "
                "no active media or playable control found"
            ),
            output=(
                "[ACN] clicking webcast candidate: Q4 Earnings Webcast\n"
                "[ACN] checking webcast registration\n"
                "[ACN] registration completed but playback was not detected\n"
            ),
            return_code=1,
        )

        status = classify_training_surface_outcome(
            result,
            selected_url=None,
            ir_url="https://investor.example.com/events#past-events",
        )
        self.assertEqual(status, "playback_failed")
        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events#past-events",
                status=status,
            ),
            "earnings",
        )

    def test_event_detail_timeout_is_not_true_playback_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1): PLAYBACK_READY_TIMED_OUT",
            output=(
                "[ALL] clicking webcast candidate: Q3 2026 Earnings Conference Call\n"
                "[ALL] candidate click failed; trying href fallback\n"
                "[ALL] click produced no navigation; opening candidate href directly: "
                "https://investor.example.com/events/event-details/q3-2026-earnings-conference-call\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )
        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
                status="candidate_discovery_retry",
            ),
            "earnings",
        )

    def test_registered_player_timeout_remains_true_playback_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1): PLAYBACK_READY_TIMED_OUT",
            output=(
                "[ABC] webcast target opened: https://provider.example.com/player\n"
                "[ABC] registration form accepted\n"
                "[ABC] registered player did not become active within 30s\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://provider.example.com/player",
                ir_url="https://investor.example.com/events",
            ),
            "playback_failed",
        )

    def test_no_registration_form_is_not_registration_success_evidence(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1): PLAYBACK_READY_TIMED_OUT",
            output=(
                "[TEST] selected event detail\n"
                "[TEST] no registration form; continuing to playback\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=(
                    "https://investor.example.com/events/event-details/"
                    "q3-2026-earnings-conference-call"
                ),
                ir_url="https://investor.example.com/events",
            ),
            "candidate_discovery_retry",
        )

    def test_archive_index_timeout_is_candidate_discovery_retry(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe timed out after 90s",
            output=(
                "clicking webcast candidate: Events & Presentations\n"
                "webcast target opened: "
                "https://loews.com/investors/events-and-presentations/default.aspx\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://loews.com/investors/events-and-presentations/default.aspx",
                ir_url="https://loews.com/investors/events-and-presentations/default.aspx",
            ),
            "candidate_discovery_retry",
        )

    def test_provider_timeout_remains_true_playback_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe timed out after 90s",
            output=(
                "webcast target opened: https://www.webcaster5.com/Webcast/Page/1302/33323\n"
                "no active media or playable control found\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://www.webcaster5.com/Webcast/Page/1302/33323",
                ir_url="https://ir.example.com/events",
            ),
            "playback_failed",
        )

    def test_stale_wsw_registration_route_is_expired(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe timed out after 90s",
            output=(
                "https://wsw.com/webcast/evercore39/register.aspx?conf=evercore39"
                "\nregistration form accepted\n"
                "registered player did not become active within 30s\n"
                "PLAYBACK_READY_TIMED_OUT\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=(
                    "https://wsw.com/webcast/evercore39/register.aspx?"
                    "conf=evercore39"
                ),
                ir_url="https://investor.example.com/events",
            ),
            "expired",
        )

    def test_expired_media_asset_is_expired(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed (exit=1)",
            output=(
                "[ZBH] media_candidate=https://wz5a.wsw.com/vod/expired.mp4/"
                "manifest.mpd?token=abc\n"
                "AUDIO_NOT_DETECTED\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://wsw.com/webcast/jeff332/zbh/1695276",
                ir_url="https://investor.example.com/events",
            ),
            "expired",
        )

    def test_registration_surface_without_selected_url_is_not_missing(self):
        result = WebcastProbeResult(
            audible=False,
            error="registration completed but playback was not detected",
            output=(
                "[ACGL] checking webcast registration\n"
                "[ACGL] registration completed but playback was not detected\n"
            ),
            return_code=1,
        )

        status = classify_training_surface_outcome(
            result,
            selected_url=None,
            ir_url="https://investor.example.com/events",
        )
        self.assertEqual(status, "playback_failed")
        self.assertEqual(
            infer_surface_kind(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
                status=status,
            ),
            "webcast",
        )

    def test_browser_navigation_error_is_not_missing_surface(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed: webcast button not found",
            output=(
                "[AEP] inspecting page for webcast controls: "
                "chrome-error://chromewebdata/\n"
                "error=webcast button not found\n"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url=None,
                ir_url="https://investor.example.com/events",
            ),
            "navigation_failed",
        )

    def test_registration_failure_is_preserved_as_downstream_failure(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed: registration form handling failed",
            output="registration form remained visible invalid_fields=1",
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://provider.example.com/register",
                ir_url="https://investor.example.com/events",
            ),
            "registration_failed",
        )

    def test_registration_submission_is_explicit_for_full_audit(self):
        self.assertFalse(parse_args([]).allow_registration_submission)
        args = parse_args(
            [
                "--allow-registration-submission",
                "--concurrency",
                "3",
                "--force",
            ]
        )
        self.assertTrue(args.allow_registration_submission)
        self.assertEqual(args.concurrency, 3)
        self.assertTrue(args.force)

    def test_registration_preview_is_explicit_and_does_not_enable_submission(self):
        args = parse_args(["--registration-preview-only"])

        self.assertTrue(args.registration_preview_only)
        self.assertFalse(args.allow_registration_submission)

    def test_registration_preview_is_classified_as_a_downstream_gate(self):
        result = WebcastProbeResult(
            audible=False,
            error="audio probe failed: REGISTRATION_PREVIEW registration submission not attempted",
            output=(
                "registration fields prepared: first_name,last_name,email\n"
                "REGISTRATION_PREVIEW {\"submission_attempted\": false}"
            ),
            return_code=1,
        )

        self.assertEqual(
            classify_training_surface_outcome(
                result,
                selected_url="https://provider.example.com/register",
                ir_url="https://investor.example.com/events",
            ),
            "registration_preview",
        )

    def test_registration_preview_json_can_be_reused_for_approval_template(self):
        preview = extract_registration_preview(
            '[DOW] REGISTRATION_PREVIEW '
            '{"ticker":"DOW","prepared_fields":["email"],'
            '"submission_attempted":false}'
        )

        self.assertEqual(preview["ticker"], "DOW")
        self.assertEqual(preview["prepared_fields"], ["email"])
        self.assertFalse(preview["submission_attempted"])

    def test_export_registration_approval_template_uses_persisted_preview(self):
        output = (
            '[DOW] REGISTRATION_PREVIEW '
            '{"ticker":"DOW","destination_url":"https://example.test/register",'
            '"prepared_fields":["company","email"],"consent_selected":true,'
            '"submission_attempted":false}'
        )
        original = audit.database.get_webcast_training_surface_targets
        audit.database.get_webcast_training_surface_targets = lambda: [
            {"ticker": "DOW", "last_output": output}
        ]
        try:
            with self.subTest("template contains only disabled approval metadata"):
                path = audit.export_registration_approval_template(
                    "/tmp/ew-registration-approval-test.json"
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    payload,
                    {
                        "schema_version": 1,
                        "approvals": {
                            "DOW": {
                                "approved": False,
                                "destination_url": "https://example.test/register",
                                "prepared_fields": ["company", "email"],
                                "consent_selected": True,
                            }
                        },
                    },
                )
        finally:
            audit.database.get_webcast_training_surface_targets = original

    def test_stored_replay_candidate_limit_is_configurable(self):
        args = parse_args(["--stored-replay-candidates", "4"])
        self.assertEqual(args.stored_replay_candidates, 4)

    def test_audit_redacts_sensitive_url_query_values(self):
        url = (
            "https://identity.q4inc.com/oauth/auth?code=secret-code&"
            "state=secret-state&prompt=none&client_id=public-client"
        )
        redacted = database.redact_sensitive_url(url)
        self.assertIn("code=%5BREDACTED%5D", redacted)
        self.assertIn("state=%5BREDACTED%5D", redacted)
        self.assertIn("client_id=public-client", redacted)
        self.assertNotIn("secret-code", redacted)
        self.assertNotIn("secret-state", redacted)
        self.assertIn(
            "state=%5BREDACTED%5D",
            database.redact_sensitive_text(f"callback={url}"),
        )


if __name__ == "__main__":
    unittest.main()
