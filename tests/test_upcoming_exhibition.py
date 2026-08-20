import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.update_exhibition import parse_target_pairs
from scripts.update_upcoming_exhibition import JST, select_upcoming_targets

ROOT = Path(__file__).resolve().parents[1]


class UpcomingExhibitionTest(unittest.TestCase):
    def test_selects_only_imminent_unfinished_races(self):
        now = datetime(2026, 8, 20, 10, 0, tzinfo=JST)
        schedules = {"13": ["09:55", "10:08", "10:15", "10:25"]}
        with patch.dict(os.environ, {
            "AUTO_MIN_REMAINING_MINUTES": "6", "AUTO_LOOKAHEAD_MINUTES": "20",
        }, clear=False):
            self.assertEqual(
                select_upcoming_targets(["13"], schedules, {("13", 2)}, now),
                [("13", 3)],
            )

    def test_parses_multiple_target_races_safely(self):
        self.assertEqual(parse_target_pairs("13-10,05-2,bad,99-1"), {("13", 10), ("05", 2)})

    def test_automation_is_scheduled_without_redeploying_data_only_commits(self):
        automatic = (ROOT / ".github" / "workflows" / "auto-upcoming-exhibition.yml").read_text(encoding="utf-8")
        pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        results = (ROOT / ".github" / "workflows" / "update-results-intraday.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "*/5 22-23,0-11 * * *"', automatic)
        self.assertIn('group: betako-data-updates', automatic)
        self.assertIn('- "data/**"', pages)
        self.assertIn('group: betako-results-updates', results)


if __name__ == "__main__":
    unittest.main()
