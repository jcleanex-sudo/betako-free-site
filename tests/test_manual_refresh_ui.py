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
        self.assertIn("const venueOptions = venues.map", script)
        self.assertIn("（本日非開催）", script)
        self.assertIn("option.disabled = !active", script)
        self.assertIn("fetchOfficialExhibitionPreview", script)
        self.assertIn("展示取得済・予想計算中", script)
        self.assertIn('`${liveDataBase}/${relative}`', script)
        self.assertIn("for (const source of sources)", script)

    def test_morning_update_does_not_dispatch_full_exhibition_sweep(self):
        workflow = (ROOT / ".github" / "workflows" / "update-predictions.yml").read_text(encoding="utf-8")
        updater = (ROOT / "scripts" / "update_exhibition.py").read_text(encoding="utf-8")

        self.assertIn("INITIALIZE_ONLY=1 python scripts/update_exhibition.py", workflow)
        self.assertNotIn("gh workflow run update-exhibition.yml", workflow)
        self.assertIn('initialize_only = os.environ.get("INITIALIZE_ONLY") == "1"', updater)


if __name__ == "__main__":
    unittest.main()
