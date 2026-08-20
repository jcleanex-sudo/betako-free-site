import unittest

from bs4 import BeautifulSoup

from scripts.fetch_race_realtime import _parse_exhibition_table, safe_float
from scripts.update_exhibition import build_fixed_portfolio, final_prediction, has_complete_portfolio


class RealtimeIntegrityTest(unittest.TestCase):
    def test_fixed_portfolio_requires_all_13_unique_tickets(self):
        complete = {
            "trifecta": [{"pick": f"1-2-{boat}"} for boat in range(1, 7)],
            "trio": [{"pick": "1-2-3"}, {"pick": "1-2-4"}],
            "exacta": [{"pick": "1-2"}, {"pick": "1-3"}],
            "quinella": [{"pick": "1-2"}, {"pick": "1-3"}, {"pick": "1-4"}],
        }
        self.assertTrue(has_complete_portfolio(complete))
        complete["quinella"].pop()
        self.assertFalse(has_complete_portfolio(complete))

    def test_safe_float_accepts_official_units(self):
        self.assertEqual(safe_float("0cm"), 0.0)
        self.assertEqual(safe_float("3m"), 3.0)
        self.assertEqual(safe_float("52.5kg"), 52.5)
        self.assertEqual(safe_float("F.03"), 0.03)

    def test_exhibition_parser_does_not_treat_boat_number_as_time(self):
        html = """
        <table class="is-w748">
          <tr><td>6</td><td>写真</td><td>選手</td><td>52.0</td><td></td><td>0.0</td></tr>
        </table>
        """
        rows = _parse_exhibition_table(BeautifulSoup(html, "lxml"))
        self.assertEqual(rows[0]["boat"], 6)
        self.assertIsNone(rows[0]["time"])

    def test_final_prediction_waits_for_course_and_start_timing(self):
        prediction = {
            "venue": "徳山", "venue_id": "18", "race": 3,
            "pick": "1-2-3", "score": 75.0,
            "contenders": [
                {"boat": boat, "relative_win_probability": probability}
                for boat, probability in enumerate((30, 22, 18, 13, 10, 7), 1)
            ],
        }
        realtime = {
            "exhibition": [
                {"boat": boat, "course": None, "time": 6.8 + boat / 100,
                 "st": None, "time_rank": boat, "st_rank": None}
                for boat in range(1, 7)
            ],
            "odds": None,
            "fetched_at": "2026-08-19T09:30:00+09:00",
            "source_url": "https://example.invalid",
        }
        result = final_prediction(prediction, realtime)
        self.assertEqual(result["status"], "WAIT")
        self.assertIn("進入・ST", result["message"])

    def test_fixed13_does_not_promote_low_probability_six_head_for_large_odds(self):
        contenders = [
            {"boat": boat, "relative_win_probability": probability}
            for boat, probability in enumerate((40, 25, 15, 10, 7, 3), 1)
        ]
        rows = []
        for market, picks in {
            "trifecta": [
                "6-1-2", "6-1-3", "6-1-4", "6-2-1", "6-2-3", "6-3-1",
                "1-2-3", "1-3-2", "1-2-4", "2-1-3", "2-3-1", "2-1-4",
            ],
            "trio": ["1-2-3", "1-2-4"],
            "exacta": ["6-1", "6-2", "1-2", "2-1"],
            "quinella": ["1-2", "1-3", "2-3"],
        }.items():
            for index, pick in enumerate(picks):
                six_head = pick.startswith("6-")
                rows.append({
                    "bet_type": market, "pick": pick, "qualifies": False,
                    "model_probability": 0.8 if six_head else 12 - index / 10,
                    "net_edge": -2 if six_head else 1,
                    "expected_profit_yen": 900 if six_head else 20,
                })
        portfolio = build_fixed_portfolio(rows, contenders)
        self.assertTrue(all(not ticket["pick"].startswith("6-") for ticket in portfolio["trifecta"]))
        self.assertTrue(all(not ticket["pick"].startswith("6-") for ticket in portfolio["exacta"]))


if __name__ == "__main__":
    unittest.main()
