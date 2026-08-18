from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ManualRefreshUiTest(unittest.TestCase):
    def test_refresh_button_and_retry_flow_are_shipped(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="refreshDataButton"', html)
        self.assertIn('id="refreshDataStatus"', html)
        self.assertIn("async function refreshAllData", script)
        self.assertIn("Promise.allSettled", script)
        self.assertIn('refreshAllData({ manual: true })', script)
        self.assertIn('window.addEventListener("offline"', script)
        self.assertIn("const venueId = String(match?.venue_id || officialVenue?.venue_id", script)
        self.assertIn("venueId,", script)
        self.assertNotIn("venueId: String(venueIndex)", script)


if __name__ == "__main__":
    unittest.main()
