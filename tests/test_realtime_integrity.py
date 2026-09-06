import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scripts.fetch_race_realtime import _parse_exhibition_table, fetch_exhibition, safe_float
from scripts.update_exhibition import (
    build_fixed_portfolio,
    build_probability_only_portfolio,
    final_prediction,
    has_complete_portfolio,
    hit_rate_priority_gate,
)


class RealtimeIntegrityTest(unittest.TestCase):
    def test_hit_rate_priority_gate_is_a_separate_shadow_filter(self):
        contenders = [
            {"boat": boat, "relative_win_probability": probability}
            for boat, probability in enumerate((72, 10, 7, 5, 4, 2), 1)
        ]
        portfolio = build_probability_only_portfolio(contenders)
        result = hit_rate_priority_gate(portfolio)
        self.assertEqual(result["mode"], "shadow_validation")
        self.assertEqual(result["status"], "CANDIDATE_BET")
        self.assertGreaterEqual(result["top_trifecta_probability"], result["threshold"])

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

    def test_exhibition_parser_reads_only_labelled_original_times(self):
        html = """
        <table><tr><th>艇番</th><th>一周タイム</th><th>まわり足</th><th>直線タイム</th></tr>
          <tr><td>1</td><td>36.40</td><td>5.60</td><td>7.20</td></tr>
          <tr><td>2</td><td>36.55</td><td>5.72</td><td>7.11</td></tr>
        </table>
        """
        rows = _parse_exhibition_table(BeautifulSoup(html, "lxml"))
        self.assertEqual(rows[0]["lap_time"], 36.40)
        self.assertEqual(rows[0]["turn_time"], 5.60)
        self.assertEqual(rows[1]["straight_time"], 7.11)

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

    def test_probability_only_portfolio_has_13_tickets_and_no_odds_inputs(self):
        contenders = [
            {"boat": boat, "relative_win_probability": probability}
            for boat, probability in enumerate((40, 25, 15, 10, 7, 3), 1)
        ]
        portfolio = build_probability_only_portfolio(contenders)
        self.assertTrue(has_complete_portfolio(portfolio))
        self.assertEqual(portfolio["trifecta"][0]["pick"], "1-2-3")
        self.assertTrue(all(
            ticket["odds"] is None and ticket["selection_basis"] == "model_probability_only"
            for tickets in portfolio.values() for ticket in tickets
        ))

    def test_complete_exhibition_can_finalize_without_odds(self):
        prediction = {
            "venue": "徳山", "venue_id": "18", "race": 3, "data_rate": 100,
            "pick": "1-2-3", "score": 75.0,
            "contenders": [
                {"boat": boat, "relative_win_probability": probability}
                for boat, probability in enumerate((30, 22, 18, 13, 10, 7), 1)
            ],
        }
        realtime = {
            "exhibition": [
                {"boat": boat, "course": boat, "time": 6.8 + boat / 100,
                 "st": f".1{boat}", "time_rank": boat, "st_rank": boat}
                for boat in range(1, 7)
            ],
            "odds": None, "wind_speed": 2, "wave_height": 1,
            "fetched_at": "2026-09-07T09:30:00+09:00",
            "source_url": "https://example.invalid",
        }

        result = final_prediction(prediction, realtime)

        self.assertEqual(result["status"], "FINAL")
        self.assertEqual(result["selection_basis"], "model_probability_only")
        self.assertTrue(has_complete_portfolio(result["portfolio"]))
        self.assertEqual(result["value"]["status"], "DATA BLOCKED")
        self.assertEqual(len(result["contenders"]), 6)
        self.assertEqual(result["original_exhibition_metrics_used"], [])

    def test_original_exhibition_only_affects_model_when_all_six_are_ranked(self):
        prediction = {
            "venue": "徳山", "venue_id": "18", "race": 3, "data_rate": 100,
            "pick": "1-2-3", "score": 75.0,
            "contenders": [
                {"boat": boat, "relative_win_probability": probability}
                for boat, probability in enumerate((30, 22, 18, 13, 10, 7), 1)
            ],
            "logic_comparison": {"legacy": {"contenders": [
                {"boat": boat, "relative_win_probability": probability}
                for boat, probability in enumerate((28, 24, 18, 13, 10, 7), 1)
            ]}},
        }
        realtime = {
            "exhibition": [
                {"boat": boat, "course": boat, "time": 6.8 + boat / 100,
                 "st": f".1{boat}", "time_rank": boat, "st_rank": boat,
                 "lap_rank": 7 - boat, "turn_rank": 7 - boat,
                 "straight_rank": 7 - boat}
                for boat in range(1, 7)
            ],
            "odds": None, "wind_speed": 2, "wave_height": 1,
            "original_exhibition_status": "available",
        }
        result = final_prediction(prediction, realtime)
        self.assertEqual(
            result["original_exhibition_metrics_used"],
            ["lap_rank", "straight_rank", "turn_rank"],
        )
        six = next(item for item in result["contenders"] if item["boat"] == 6)
        self.assertGreater(six["original_exhibition_adjustment"], 0)
        self.assertTrue(has_complete_portfolio(result["legacy_probability_portfolio"]))
        self.assertEqual(result["logic_ab"]["sampling"], "same_race_same_exhibition")

    @patch("scripts.fetch_race_realtime.fetch_all_odds")
    @patch("scripts.fetch_race_realtime._fetch_html", return_value="<html></html>")
    def test_live_exhibition_does_not_fetch_reference_odds_by_default(self, _fetch_html, fetch_odds):
        rows = [
            {"boat": boat, "course": boat, "time": 6.8 + boat / 100,
             "st": f".1{boat}", "tilt": 0, "weight": 52}
            for boat in range(1, 7)
        ]
        with (
            patch("scripts.fetch_race_realtime._parse_exhibition_table", return_value=rows),
            patch.dict("scripts.fetch_race_realtime.os.environ", {}, clear=True),
        ):
            result = fetch_exhibition("18", 3, "20260907")
        self.assertEqual(len(result["exhibition"]), 6)
        fetch_odds.assert_not_called()


if __name__ == "__main__":
    unittest.main()
