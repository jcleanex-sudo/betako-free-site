import unittest
from unittest.mock import patch

from scripts.evaluate_results import build_today_venue_performance, evaluate_fixed_portfolios


class TodayVenuePerformanceTest(unittest.TestCase):
    def test_only_completed_results_are_counted_and_small_sample_is_not_hot(self):
        history = {"all_races": [
            {"venue_id": "01", "venue": "桐生", "race": 1, "pick": "1-2-3", "data_rate": 100,
             "contenders": [{"boat": boat} for boat in (1, 2, 3, 4)]},
            {"venue_id": "01", "venue": "桐生", "race": 2, "pick": "1-2-3", "data_rate": 100,
             "contenders": [{"boat": boat} for boat in (1, 2, 3, 4)]},
        ]}
        with patch("scripts.evaluate_results.fetch_result", side_effect=[("1-2-3", 1200), None]):
            result = build_today_venue_performance("20260815", history)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["venues"][0]["hits"], 1)
        self.assertEqual(result["venues"][0]["status"], "サンプル不足")

    def test_data_blocked_prediction_is_excluded(self):
        history = {"all_races": [{
            "venue_id": "01", "venue": "桐生", "race": 1, "pick": "1-2-3",
            "data_rate": 80, "label": "DATA BLOCKED", "contenders": [],
        }]}
        with patch("scripts.evaluate_results.fetch_result") as fetch:
            result = build_today_venue_performance("20260815", history)
        fetch.assert_not_called()
        self.assertEqual(result["records"], {})

    def test_complete_watch_fixed13_is_still_evaluated(self):
        portfolio = {
            "trifecta": [{"pick": pick} for pick in ("1-2-3", "1-3-2", "2-1-3", "2-3-1", "3-1-2", "3-2-1")],
            "trio": [{"pick": pick} for pick in ("1-2-3", "1-2-4")],
            "exacta": [{"pick": pick} for pick in ("1-2", "2-1")],
            "quinella": [{"pick": pick} for pick in ("1-2", "1-3", "2-3")],
        }
        exhibition = {"races": [{
            "venue_id": "01", "venue": "桐生", "race": 1, "status": "FINAL",
            "value": {"status": "WATCH", "data_rate": 100, "portfolio": portfolio},
        }]}
        official = {
            "trifecta": {"pick": "1-2-3", "payout_yen": 1200},
            "trio": {"pick": "1-2-3", "payout_yen": 400},
            "exacta": {"pick": "1-2", "payout_yen": 500},
            "quinella": {"pick": "1-2", "payout_yen": 300},
        }
        with patch("scripts.evaluate_results.fetch_all_results", return_value=official):
            records = evaluate_fixed_portfolios("20260820", exhibition, {})
        record = records["20260820-01-1-fixed13"]
        self.assertTrue(record["hit"])
        self.assertEqual(record["hit_count"], 4)
        self.assertEqual(record["stake_yen"], 1300)


if __name__ == "__main__":
    unittest.main()
