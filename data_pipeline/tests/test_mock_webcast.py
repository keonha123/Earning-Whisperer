import unittest

from data_pipeline.tools.mock.mock_webcast_server import (
    MOCK_HTML,
    MockWebcastHandler,
    build_wav_bytes,
)


class MockWebcastFixtureTest(unittest.TestCase):
    def test_fixture_contains_registration_and_playback_controls(self):
        self.assertIn('id="registration-form"', MOCK_HTML)
        self.assertIn('name="industry_affiliation"', MOCK_HTML)
        self.assertIn('aria-label="Play webcast"', MOCK_HTML)
        self.assertIn('<video id="webcast-video"', MOCK_HTML)
        self.assertIn('src="/sample.mp4"', MOCK_HTML)

    def test_fixture_audio_is_a_valid_pcm_wav(self):
        payload = build_wav_bytes(duration_seconds=1)
        self.assertEqual(payload[:4], b"RIFF")
        self.assertEqual(payload[8:12], b"WAVE")
        self.assertGreater(len(payload), 16_000)

    def test_silent_browser_fixture_keeps_a_direct_media_fallback_candidate(self):
        MockWebcastHandler.set_silent_browser_audio(True)
        try:
            payload = MockWebcastHandler.page_payload().decode("utf-8")
        finally:
            MockWebcastHandler.set_silent_browser_audio(False)

        self.assertIn('src="/silent.mp4"', payload)
        self.assertIn('id="fallback-audio-candidate" src="/audio.mp4"', payload)


if __name__ == "__main__":
    unittest.main()
