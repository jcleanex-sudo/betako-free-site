import unittest

from bs4 import BeautifulSoup

from scripts.generate_predictions import make_prediction, parse_entry


class PredictionDetailsTest(unittest.TestCase):
    def test_racelist_parser_keeps_detailed_official_statistics(self):
        html = """
        <tbody class="is-fs12"><tr>
          <td>１</td><td>写真</td>
          <td><a href="?toban=4321"><span class="is-fs18">水面 太郎</span>4321 / A1 35歳 52.0kg</a></td>
          <td>F1 L0 0.15</td>
          <td>6.25 48.5 66.7</td><td>5.80 42.0 61.0</td>
          <td>17 39.5 57.2</td><td>21 35.0 54.0</td>
        </tr></tbody>
        """
        entry = parse_entry(BeautifulSoup(html, "lxml").tbody, "18")
        self.assertEqual(entry["registration_number"], "4321")
        self.assertEqual(entry["age"], 35)
        self.assertEqual(entry["national_2rate"], 48.5)
        self.assertEqual(entry["national_3rate"], 66.7)
        self.assertEqual(entry["local_3rate"], 61.0)
        self.assertEqual(entry["motor_3rate"], 57.2)
        self.assertEqual(entry["boat_3rate"], 54.0)
        self.assertEqual(entry["f_count"], 1)
        self.assertEqual(entry["l_count"], 0)

    def test_prediction_exposes_six_boat_comparison_without_fabricating_optional_data(self):
        entries = []
        for boat in range(1, 7):
            entries.append({
                "boat": boat, "name": f"選手{boat}", "class": "A2", "stadium": "18",
                "national": 6.0 - boat / 10, "national_2rate": 45 - boat,
                "national_3rate": 62 - boat, "local": 5.5 - boat / 10,
                "local_2rate": 40 - boat, "local_3rate": 58 - boat,
                "motor": 38 - boat, "motor_3rate": 55 - boat,
                "boat_rate": 34 - boat, "boat_3rate": 51 - boat,
                "st": .14 + boat / 100, "f_count": 0, "l_count": 0,
                "course_specific": None, "must_win_status": "unavailable",
                "current_meet_results": None, "age": None, "weight": None,
                "registration_number": None,
            })
        prediction = make_prediction("18", 1, entries)
        self.assertEqual(len(prediction["contenders"]), 6)
        self.assertIn("全国/当地2連3連率", prediction["logic"])
        self.assertTrue(all(item["must_win_status"] == "unavailable" for item in prediction["contenders"]))
        self.assertTrue(any("推測しない" in reason for reason in prediction["reasons"]))


if __name__ == "__main__":
    unittest.main()
