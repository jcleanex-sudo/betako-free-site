import unittest

from scripts.backfill_portfolio_variants import paired_comparison


class BackfillPortfolioVariantsTest(unittest.TestCase):
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
