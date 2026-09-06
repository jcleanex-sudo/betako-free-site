import unittest

from scripts.backfill_portfolio_variants import hit_rate_priority_summary, paired_comparison


class BackfillPortfolioVariantsTest(unittest.TestCase):
    def test_hit_rate_priority_summary_keeps_training_and_holdout_separate(self):
        records = {}
        for race in range(10):
            key = f"202609{race + 1:02d}-01-1-backtest-probability-only"
            records[key] = {
                "key": key,
                "strategy": "probability_only",
                "hit": race != 8,
                "profit_yen": 100 if race != 8 else -100,
                "tickets": [{
                    "bet_type": "trifecta",
                    "model_probability": 8 if race < 9 else 6,
                }],
            }
        summary = hit_rate_priority_summary(records)
        self.assertEqual(summary["status"], "CANDIDATE_ONLY")
        self.assertEqual(summary["overall"]["samples"], 9)
        self.assertEqual(summary["training_70pct"]["samples"], 7)
        self.assertEqual(summary["holdout_30pct"]["samples"], 2)

    def test_paired_comparison_counts_only_same_races(self):
        records = {}
        outcomes = [(True, True), (True, False), (False, True), (False, False)]
        for race, (odds_hit, probability_hit) in enumerate(outcomes, start=1):
            for strategy, hit, suffix, profit in (
                ("odds_aware", odds_hit, "backtest-odds-aware", 100 if odds_hit else -100),
                ("probability_only", probability_hit, "backtest-probability-only", 200 if probability_hit else -100),
            ):
                key = f"20260901-01-{race}-{suffix}"
                records[key] = {
                    "key": key, "venue_id": "01", "race": race,
                    "strategy": strategy, "hit": hit, "profit_yen": profit,
                }

        comparison = paired_comparison(records)

        self.assertEqual(comparison["pairs"], 4)
        self.assertEqual(comparison["both_hit"], 1)
        self.assertEqual(comparison["odds_aware_only_hit"], 1)
        self.assertEqual(comparison["probability_only_hit"], 1)
        self.assertEqual(comparison["both_miss"], 1)
        self.assertEqual(comparison["hit_rate_difference_points"], 0.0)
        self.assertEqual(comparison["net_profit_difference_yen"], 200)


if __name__ == "__main__":
    unittest.main()
