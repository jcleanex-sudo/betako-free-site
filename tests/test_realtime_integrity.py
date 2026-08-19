import unittest

from bs4 import BeautifulSoup

from scripts.fetch_race_realtime import _parse_exhibition_table, safe_float
from scripts.update_exhibition import final_prediction


class RealtimeIntegrityTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
