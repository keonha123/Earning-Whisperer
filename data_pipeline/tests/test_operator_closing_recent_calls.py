"""Regression cases from the MU/JBL recordings and adverse continuations."""
import unittest

from data_pipeline.live_end import TranscriptEndObserver, explicit_operator_close

MU_CLOSE = "This concludes the Q&A session and today's call. Thank you for attending. You may now disconnect."
JBL_CLOSE = ("Thank you. At this time, I'd like to turn the floor back over to Mr. Berry for closing comments. "
             "Thank you very much. This concludes our call. Ladies and gentlemen, thank you for your participation. "
             "This concludes today's event. You may disconnect your lines or log off the webcast.")
JBL_FOLLOWUP = "Connect your lines or log off the webcast at this time and enjoy the rest of your day."


class RecentClosingTest(unittest.TestCase):
    def prepared(self):
        observer = TranscriptEndObserver()
        for i in range(12):
            observer.observe('Our revenue and operating margin improved this quarter.',
                             audio_seconds=20*(i+1), backlog_seconds=0)
        return observer

    def test_actual_mu_close_needs_processed_quiet_and_low_backlog(self):
        observer = self.prepared()
        self.assertTrue(explicit_operator_close(MU_CLOSE))
        self.assertIsNone(observer.observe(MU_CLOSE, audio_seconds=260, backlog_seconds=0))
        for stamp in (280, 300):
            self.assertIsNone(observer.observe('', audio_seconds=stamp, backlog_seconds=0))
        self.assertIsNone(observer.observe('', audio_seconds=320, backlog_seconds=30))
        result = observer.observe('', audio_seconds=340, backlog_seconds=0)
        self.assertEqual(result['post_close_audio_seconds'], 80)

    def test_actual_jbl_followup_and_thanks_restart_quiet_period(self):
        observer = self.prepared()
        observer.observe(JBL_CLOSE, audio_seconds=260, backlog_seconds=0)
        self.assertIsNotNone(observer.candidate)
        for text, stamp in [(JBL_FOLLOWUP, 280), ('Thank you.', 300)]:
            self.assertIsNone(observer.observe(text, audio_seconds=stamp, backlog_seconds=0))
            self.assertEqual(observer.candidate['closing_audio_seconds'], stamp)
            self.assertEqual(observer.quiet_windows, 0)
        self.assertIsNone(observer.observe('', audio_seconds=320, backlog_seconds=0))
        self.assertIsNone(observer.observe('[music]', audio_seconds=340, backlog_seconds=0))
        result = observer.observe('', audio_seconds=360, backlog_seconds=0)
        self.assertEqual(result['post_close_audio_seconds'], 60)
        self.assertTrue(result['text'].endswith(JBL_CLOSE))

    def test_courtesy_and_disconnect_followup_cannot_start_closing(self):
        for text in (JBL_FOLLOWUP, 'Thank you.', 'Have a wonderful day.',
                     'You may now disconnect.', '[music]'):
            with self.subTest(text=text):
                observer = self.prepared()
                observer.observe(text, audio_seconds=260, backlog_seconds=0)
                self.assertIsNone(observer.candidate)
                self.assertIsNone(observer.observe('', audio_seconds=1000, backlog_seconds=0))

    def test_joint_qa_call_closure_variants_still_require_disconnect(self):
        for text in ("This concludes the question and answer session and our conference call. You may now disconnect.",
                     "This concludes our Q&A and today's earnings call. You may disconnect your telephone lines."):
            self.assertTrue(explicit_operator_close(text), text)
        for text in ("This concludes the Q&A session. You may now disconnect.",
                     "This concludes the Q&A session, but not today's call. You may now disconnect.",
                     "This concludes the Q&A session and today's call.",
                     "If this concludes the Q&A session and today's call, you may now disconnect.",
                     "The announcement said this concludes the Q&A session and today's call. You may now disconnect.",
                     "This concludes our call option discussion. You may now disconnect.",
                     "This concludes our call. You may now disconnect our legacy network."):
            self.assertFalse(explicit_operator_close(text), text)

    def test_substantive_or_short_resumed_speech_cancels_even_after_courtesy(self):
        for text in ('Please hold.', 'Another question?', 'Yes.', "Don't disconnect.",
                     'Thank you. Our revenue increased ten percent.',
                     'Thank you for the question.', 'Have a good day, but first an update.',
                     'Connect your lines to our new network for improved margins.'):
            with self.subTest(text=text):
                observer = self.prepared()
                observer.observe(JBL_CLOSE, audio_seconds=260, backlog_seconds=0)
                observer.observe(JBL_FOLLOWUP, audio_seconds=280, backlog_seconds=0)
                observer.observe(text, audio_seconds=300, backlog_seconds=0)
                self.assertIsNone(observer.candidate)
                self.assertIsNone(observer.observe('', audio_seconds=1000, backlog_seconds=0))

    def test_continuous_courtesy_is_never_counted_as_quiet(self):
        observer = self.prepared()
        observer.observe(MU_CLOSE, audio_seconds=260, backlog_seconds=0)
        for stamp in range(280, 1200, 20):
            self.assertIsNone(observer.observe('Thank you.', audio_seconds=stamp, backlog_seconds=0))
            self.assertEqual(observer.quiet_windows, 0)

    def test_duplicate_or_nonfinite_audio_cannot_manufacture_quiet(self):
        observer = self.prepared()
        observer.observe(MU_CLOSE, audio_seconds=260, backlog_seconds=0)
        observer.observe('', audio_seconds=320, backlog_seconds=0)
        for stamp in (320, 300, float('nan'), float('inf')):
            self.assertIsNone(observer.observe('', audio_seconds=stamp, backlog_seconds=0))
            self.assertEqual(observer.quiet_windows, 1)
        self.assertIsNone(observer.observe('', audio_seconds=340, backlog_seconds=-1))
        self.assertIsNotNone(observer.observe('', audio_seconds=360, backlog_seconds=0))


if __name__ == '__main__':
    unittest.main()
