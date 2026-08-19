import threading
import time
import unittest
from unittest.mock import patch

from scripts import fetch_race_realtime


class ParallelOddsRefreshTest(unittest.TestCase):
    def test_unquoted_combination_does_not_block_fixed_13(self):
        minimums = fetch_race_realtime.MINIMUM_PUBLISHABLE_MARKET_COUNTS
        self.assertLessEqual(minimums["trifecta"], 120)
        self.assertLessEqual(minimums["trio"], 20)
        self.assertLessEqual(minimums["exacta"], 30)
        self.assertLessEqual(minimums["quinella"], 14)
        self.assertEqual(minimums, {
            "single": 1, "exacta": 2, "quinella": 3, "trio": 2, "trifecta": 6,
        })

    def _measure_concurrency(self, targeted):
        lock = threading.Lock()
        active = 0
        maximum = 0

        def fake_fetch(_path, _params):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return "<html></html>"

        environment = {"TARGET_VENUE_ID": "10", "TARGET_RACE": "1"} if targeted else {}
        with patch.dict("os.environ", environment, clear=True), patch.object(
            fetch_race_realtime, "_fetch_html", side_effect=fake_fetch
        ):
            fetch_race_realtime.fetch_all_odds("10", 1, "20260819")
        return maximum

    def test_targeted_refresh_fetches_market_pages_concurrently(self):
        self.assertGreaterEqual(self._measure_concurrency(targeted=True), 2)

    def test_full_sweep_keeps_market_pages_sequential(self):
        self.assertEqual(self._measure_concurrency(targeted=False), 1)


if __name__ == "__main__":
    unittest.main()
