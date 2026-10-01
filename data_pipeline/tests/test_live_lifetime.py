"""Real local browser/process lifetime tests: no external network or service."""
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.lifetime import (
    current_event_end_evidence, hold_playback, read_current_termination,
    watch_sources, write_termination, ENDED_TEXT,
)


class RunEnvironment:
    def start_environment(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.marker = Path(self.temporary.name) / "termination.json"
        self.environment = mock.patch.dict(os.environ, {
            "WEBCAST_SUPERVISED_LIVE": "true",
            "WEBCAST_LIVE_TERMINATION_FILE": str(self.marker),
            "WEBCAST_LIVE_RUN_ID": "current-run",
            "WEBCAST_LIVE_RUN_STARTED_AT": str(time.time()),
            "CALL_ID": "TEST-session",
            "STT_CAPTURE_SESSION_ID": "TEST-session",
            "TICKER": "TEST",
            "WEBCAST_TARGET_DATE": "2026-09-18",
            "WEBCAST_LIVE_END_POLL_SECONDS": ".05",
            "WEBCAST_LIVE_END_CONFIRM_SECONDS": ".1",
        })
        self.environment.start()
    def stop_environment(self):
        self.environment.stop()
        self.temporary.cleanup()


class EndTextTest(unittest.TestCase):
    def test_provider_end_clause_accepts_comma_without_matching_word_prefix(self):
        for text in (
            "Broadcast has ended, thanks for watching!",
            "This webcast has ended; thank you.",
            "This Webcast has concluded.",
        ):
            self.assertIsNotNone(ENDED_TEXT.search(text), text)
        for text in ("Broadcast has endedness", "Next webcast has ended.",
                     "Broadcast has ended? Please refresh to check."):
            self.assertIsNone(ENDED_TEXT.search(text), text)


class SourceSupervisorTest(RunEnvironment, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.start_environment()
        self.children = []
    async def asyncTearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            await asyncio.to_thread(child.wait, timeout=3)
        self.stop_environment()
    def child(self, delay=30):
        process = subprocess.Popen([sys.executable, "-c", f"import time;time.sleep({delay})"])
        self.children.append(process)
        return process

    def positive_end(self):
        return write_termination(
            "event_ended", verified=True, evidence="This event has ended.",
            url="https://event.webcasts.com/starthere.jsp?ei=123",
            proof={"verified": True, "call_ticker": "TEST", "target_date": "2026-09-18"},
        )

    async def test_browser_loss_stops_pcm_and_records_retryable_reason(self):
        browser, pcm = self.child(.15), self.child()
        reason = await asyncio.to_thread(
            watch_sources, browser.pid, pcm.pid, [],
            poll_seconds=.02, loss_grace_seconds=.04, tail_seconds=0,
        )
        self.assertEqual(reason, "source_lost")
        await asyncio.to_thread(pcm.wait, timeout=2)
        marker = read_current_termination(self.marker)
        self.assertEqual(marker["reason"], "source_lost")
        self.assertFalse(marker["target_identity_verified"])

    async def test_live_fallback_survives_browser_exit_then_reports_its_own_loss(self):
        browser, fallback, pcm = self.child(.03), self.child(), self.child()
        watcher = asyncio.create_task(asyncio.to_thread(
            watch_sources, browser.pid, pcm.pid, [fallback.pid],
            poll_seconds=.02, loss_grace_seconds=.04, tail_seconds=0,
        ))
        await asyncio.sleep(.15)
        self.assertFalse(watcher.done())
        self.assertIsNone(pcm.poll())
        self.assertFalse(self.marker.exists())
        fallback.terminate()
        self.assertEqual(await asyncio.wait_for(watcher, 2), "source_lost")

    async def test_selected_fallback_loss_is_not_hidden_by_an_idle_browser(self):
        browser, fallback, pcm = self.child(), self.child(.1), self.child()
        reason = await asyncio.to_thread(
            watch_sources, browser.pid, pcm.pid, [fallback.pid],
            poll_seconds=.02, loss_grace_seconds=.04, tail_seconds=0,
        )
        self.assertEqual(reason, "source_lost")
        self.assertIsNone(browser.poll())

    async def test_positive_event_end_closes_pcm_and_survives_later_loss_write(self):
        browser, pcm = self.child(), self.child()
        self.positive_end()
        reason = await asyncio.to_thread(
            watch_sources, browser.pid, pcm.pid, [],
            poll_seconds=.02, loss_grace_seconds=.04, tail_seconds=0,
        )
        self.assertEqual(reason, "event_ended")
        write_termination("source_lost")
        self.assertEqual(read_current_termination(self.marker)["reason"], "event_ended")

    async def test_already_dead_selected_fallback_is_not_replaced_by_browser(self):
        browser, fallback, pcm = self.child(), self.child(.01), self.child()
        await asyncio.to_thread(fallback.wait, timeout=2)
        reason = await asyncio.to_thread(
            watch_sources, browser.pid, pcm.pid, [fallback.pid],
            poll_seconds=.02, loss_grace_seconds=.04, tail_seconds=0,
        )
        self.assertEqual(reason, "source_lost")
        self.assertIsNone(browser.poll())
        await asyncio.to_thread(pcm.wait, timeout=2)

    def test_stale_other_run_cannot_prove_completion(self):
        self.positive_end()
        with mock.patch.dict(os.environ, {"WEBCAST_LIVE_RUN_ID": "next-run"}):
            self.assertIsNone(read_current_termination(self.marker))
            write_termination("source_lost")
            self.assertEqual(read_current_termination(self.marker)["reason"], "source_lost")
        self.assertEqual(self.marker.stat().st_mode & 0o777, 0o600)

    def test_unverified_or_wrong_event_marker_is_not_authoritative(self):
        self.positive_end()
        original = json.loads(self.marker.read_text())
        for field, value in (("target_identity_verified", False), ("reason", "timeout")):
            bad = {**original, field: value}
            self.marker.write_text(json.dumps(bad))
            self.assertIsNone(read_current_termination(self.marker))
        original["event_identity"]["call_ticker"] = "OTHER"
        self.marker.write_text(json.dumps(original))
        self.assertIsNone(read_current_termination(self.marker))


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires local Chromium")
class BrowserLifetimeTest(RunEnvironment, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.start_environment()
        from playwright.async_api import async_playwright
        from data_pipeline.collectors.streams.browser.navigation import (
            make_target_proof, validate_target_page,
        )
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html",
            body="<h1>Current earnings call</h1><video controls></video>",
        ))
        await self.page.goto("https://event.webcasts.com/starthere.jsp?ei=123")
        self.agent = SimpleNamespace(
            lifecycle="live", hold_seconds=.03, ticker="TEST",
            target_date=date(2026, 9, 18), _live_redirect_edges=set(),
        )
        self.agent.live_target_proof = make_target_proof(
            self.agent, "https://issuer.test/events", self.page.url, "official dated event",
        )
        async def validate(page):
            return await validate_target_page(self.agent, page)
        self.agent._validate_live_target_page = validate
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
        await self.browser.close()
        await self.playwright.stop()
        self.stop_environment()

    async def test_supervised_live_stays_past_hold_and_requires_sustained_end(self):
        task = asyncio.create_task(hold_playback(self.agent, self.page))
        self.tasks.append(task)
        await asyncio.sleep(.15)
        self.assertFalse(task.done())
        await self.page.set_content(
            '<h1>Current earnings call</h1><div role="status">This webcast has ended.</div>'
        )
        await asyncio.sleep(.04)
        self.assertFalse(task.done())
        await asyncio.wait_for(asyncio.shield(task), 2)
        self.assertFalse(self.page.is_closed())
        marker = read_current_termination(self.marker)
        self.assertEqual(marker["reason"], "event_ended")
        self.assertTrue(marker["target_identity_verified"])
        self.assertEqual(marker["event_identity"]["provider_event_id"], "webcasts:123")

    async def test_replay_and_unsupervised_live_keep_bounded_hold(self):
        self.agent.lifecycle = "replay"
        await asyncio.wait_for(hold_playback(self.agent, self.page), .3)
        self.agent.lifecycle = "live"
        with mock.patch.dict(os.environ, {"WEBCAST_SUPERVISED_LIVE": "false"}):
            await asyncio.wait_for(hold_playback(self.agent, self.page), .3)
        self.assertFalse(self.marker.exists())

    async def test_plain_body_other_event_and_media_ended_are_not_completion(self):
        for document in (
            '<p>This webcast has ended.</p><video></video>',
            '<article data-event-id="999"><div role="status">This webcast has ended.</div></article>',
            '<div role="status">This webcast has ended. December 9, 2026</div>',
            '<div role="status" hidden>This webcast has ended.</div>',
            '<video></video>',
        ):
            await self.page.set_content(document)
            self.assertIsNone(await current_event_end_evidence(self.agent, self.page), document)
        await self.page.locator("video").evaluate("el => Object.defineProperty(el, 'ended', {value:true})")
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_active_media_contradicts_stale_status(self):
        await self.page.set_content('<div role="status">This webcast has ended.</div><video></video>')
        await self.page.locator("video").evaluate("""el => {
            Object.defineProperty(el, 'ended', {value:false});
            Object.defineProperty(el, 'paused', {value:false});
            Object.defineProperty(el, 'readyState', {value:3});
        }""")
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_same_event_iframe_active_media_vetoes_parent_end_status(self):
        await self.page.set_content(
            '<div role="status">This webcast has ended.</div>'
            '<iframe src="https://event.webcasts.com/player.jsp?ei=123"></iframe>'
        )
        frame = next(frame for frame in self.page.frames if frame is not self.page.main_frame)
        await frame.wait_for_selector("video")
        await frame.locator("video").evaluate("""el => {
            Object.defineProperty(el, 'ended', {value:false});
            Object.defineProperty(el, 'paused', {value:false});
            Object.defineProperty(el, 'readyState', {value:3});
        }""")
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_provider_modal_title_before_webinar_end_leaf(self):
        await self.page.set_content(
            '<div class="modal-content" role="dialog"><h2>Lennar Q3 Earnings Call</h2>'
            '<p>The webinar has ended.</p></div>'
        )
        self.assertEqual(await current_event_end_evidence(self.agent, self.page),
                         "The webinar has ended.")

    async def prepare_q4_event(self):
        from data_pipeline.collectors.streams.browser.navigation import make_target_proof
        await self.page.goto("https://events.q4inc.com/attendee/120777763/guest")
        self.agent.live_target_proof = make_target_proof(
            self.agent, "https://issuer.test/events", self.page.url, "official dated event",
        )

    async def test_q4_current_event_plain_end_notice_is_recognized_and_sustained(self):
        await self.prepare_q4_event()
        notice = "Broadcast has ended, thanks for watching!"
        await self.page.set_content(
            '<h1>Q1 F27 Earnings Call</h1><div><span>' + notice + '</span>'
            '<p>If you experienced any issues, please contact support.</p></div><video></video>'
        )
        self.assertEqual(await current_event_end_evidence(self.agent, self.page), notice)
        task = asyncio.create_task(hold_playback(self.agent, self.page))
        self.tasks.append(task)
        await asyncio.sleep(.04)
        self.assertFalse(task.done())
        await asyncio.wait_for(asyncio.shield(task), 2)
        marker = read_current_termination(self.marker)
        self.assertEqual(marker["reason"], "event_ended")
        self.assertEqual(marker["evidence"], notice)

    async def test_q4_other_content_hidden_or_active_media_is_not_completion(self):
        await self.prepare_q4_event()
        notice = "Broadcast has ended, thanks for watching!"
        for wrapper in (
            '<article><div>{}</div></article>',
            '<article data-event-id="999"><div>{}</div></article>',
            '<section data-event-id="999"><div>{}</div></section>',
            '<nav><div>{}</div></nav>',
            '<a href="/attendee/999">{}</a>',
            '<div hidden>{}</div>',
        ):
            await self.page.set_content('<h1>Q1 F27 Earnings Call</h1>' + wrapper.format(notice))
            self.assertIsNone(await current_event_end_evidence(self.agent, self.page), wrapper)
        await self.page.set_content('<div>' + notice + '</div><video></video>')
        await self.page.locator("video").evaluate("""el => {
            Object.defineProperty(el, 'ended', {value:false});
            Object.defineProperty(el, 'paused', {value:false});
            Object.defineProperty(el, 'readyState', {value:3});
        }""")
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_q4_different_event_redirect_and_unrelated_iframe_cannot_end(self):
        await self.prepare_q4_event()
        notice = "Broadcast has ended, thanks for watching!"
        await self.page.set_content('<iframe src="https://events.q4inc.com/attendee/999/guest"></iframe>')
        frame = next(frame for frame in self.page.frames if frame is not self.page.main_frame)
        await frame.wait_for_selector("video")
        await frame.locator("body").evaluate(
            "(el, html) => { el.innerHTML = html; }", '<div role="status">' + notice + '</div>',
        )
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))
        # Even a recorded redirect must not lend the old event proof to another
        # Q4 numeric event. Generic navigation has no Q4 ID shortcut today.
        expected = self.page.url
        other = "https://events.q4inc.com/attendee/999/guest"
        self.agent._live_redirect_edges.add((expected, other))
        await self.page.goto(other)
        await self.page.set_content('<div role="status">' + notice + '</div>')
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_q4_other_event_active_iframe_vetoes_even_plain_end_notice(self):
        await self.prepare_q4_event()
        await self.page.set_content(
            '<div>Broadcast has ended, thanks for watching!</div>'
            '<iframe src="https://events.q4inc.com/attendee/999/guest"></iframe>'
        )
        frame = next(frame for frame in self.page.frames if frame is not self.page.main_frame)
        await frame.wait_for_selector("video")
        await frame.locator("video").evaluate("""el => {
            Object.defineProperty(el, 'ended', {value:false});
            Object.defineProperty(el, 'paused', {value:false});
            Object.defineProperty(el, 'readyState', {value:3});
        }""")
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_different_event_route_cannot_finish_current_call(self):
        await self.page.goto("https://event.webcasts.com/starthere.jsp?ei=999")
        await self.page.set_content('<div role="status">This webcast has ended.</div>')
        self.assertIsNone(await current_event_end_evidence(self.agent, self.page))

    async def test_closed_player_is_source_loss_not_event_completion(self):
        await self.page.close()
        with self.assertRaisesRegex(RuntimeError, "LIVE_SOURCE_LOST"):
            await hold_playback(self.agent, self.page)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
