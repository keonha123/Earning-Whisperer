"""Opt-in real Chromium test; all navigation is to a local fixture server."""

import asyncio
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from data_pipeline import database
from data_pipeline.collectors.streams.browser_webcast import BrowserWebcastAgent, InvestorProfile
from data_pipeline.tools.mock.mock_webcast_server import MockWebcastHandler


class FixtureHandler(MockWebcastHandler):
    def do_GET(self):
        if self.path == "/events":
            body = b'<h1>EWTEST Earnings Call</h1><a href="/webcast" target="_blank">Listen to the webcast</a>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class LocalBrowserComponentsTest(unittest.TestCase):
    def test_discover_register_and_play_without_human_handoff(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stack.callback(server.server_close)
            stack.callback(thread.join, 5)
            stack.callback(server.shutdown)
            stack.enter_context(mock.patch.dict(os.environ, {
                "PATH": os.getenv("PATH", "/usr/bin:/bin"),
                "HOME": directory,
                "PLAYWRIGHT_BROWSERS_PATH": os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright"),
                "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true",
                "WEBCAST_REGISTRATION_REQUIRE_APPROVAL": "false",
                "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false",
                "WEBCAST_LIFECYCLE": "unknown",
                "WEBCAST_PLAYBACK_READY_FILE": str(Path(directory) / "ready"),
                "WEBCAST_ARTIFACTS_DIR": directory,
                "WEBCAST_RECIPE_CONTEXT_FILE": str(Path(directory) / "recipe.json"),
                "WEBCAST_REPLAY_SEEK_SECONDS": "0",
                "MOCK_WEBCAST_AUDIO_MODE": "tone",
            }, clear=True))
            for name in ("get_verified_webcast_recipes", "get_verified_human_workflows", "get_generalized_webcast_patterns"):
                stack.enter_context(mock.patch.object(database, name, return_value=[]))
            stack.enter_context(mock.patch.object(database, "save_webcast_recipe", return_value=1))
            stack.enter_context(mock.patch.object(database, "record_webcast_recipe_outcome"))
            profile = InvestorProfile("test@example.test", "", "Test", "User", "Example")
            agent = BrowserWebcastAgent(
                "EWTEST", f"http://127.0.0.1:{server.server_port}/events",
                profile=profile,
                storage_state_path=str(Path(directory) / "state.json"),
            )
            result = asyncio.run(asyncio.wait_for(agent.run(), timeout=120))
            self.assertTrue(result.success, result.error)
            self.assertTrue(result.playback_triggered)
            self.assertTrue(result.final_url.endswith("/webcast"), result.final_url)
            self.assertTrue((Path(directory) / "ready").exists())
            self.assertEqual(agent._human_handoff_count, 0)
