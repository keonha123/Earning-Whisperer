import unittest

from data_pipeline.tools.replay.historical_replay_learning_batch import parse_args


class HistoricalReplayLearningBatchTest(unittest.TestCase):
    def test_accepts_ticker_subset_for_targeted_verification(self):
        args = parse_args(["--tickers", "A,ABBV,ABT", "--limit", "4"])

        self.assertEqual(args.tickers, "A,ABBV,ABT")
        self.assertEqual(args.limit, 4)

    def test_registration_submission_requires_explicit_flag(self):
        self.assertFalse(parse_args([]).allow_registration_submission)
        self.assertTrue(
            parse_args(["--allow-registration-submission"]).allow_registration_submission
        )

    def test_authentication_retry_requires_explicit_flag(self):
        self.assertFalse(parse_args([]).retry_auth_required)
        self.assertTrue(parse_args(["--retry-auth-required"]).retry_auth_required)

    def test_auth_required_only_requires_explicit_flag(self):
        self.assertFalse(parse_args([]).auth_required_only)
        self.assertTrue(parse_args(["--auth-required-only"]).auth_required_only)

    def test_supports_generalized_learning_ab_comparison_flag(self):
        self.assertTrue(parse_args(["--disable-generalized-learning"]).disable_generalized_learning)

    def test_accepts_replay_source_kind_filter(self):
        args = parse_args(["--source-kinds", "ir_entrypoint"])

        self.assertEqual(args.source_kinds, "ir_entrypoint")


if __name__ == "__main__":
    unittest.main()
