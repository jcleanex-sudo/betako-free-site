"""Automatically update imminent races without requiring a page visit."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

try:
    from .fetch_race_realtime import _fetch_html, _parse_deadline
    from .update_exhibition import main as update_exhibition
except ImportError:  # Direct script execution in GitHub Actions.
    from fetch_race_realtime import _fetch_html, _parse_deadline
    from update_exhibition import main as update_exhibition


JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "predictions.json"
EXHIBITION = ROOT / "data" / "exhibition.json"
MIN_REMAINING_MINUTES = int(os.environ.get("AUTO_MIN_REMAINING_MINUTES", "6"))
LOOKAHEAD_MINUTES = int(os.environ.get("AUTO_LOOKAHEAD_MINUTES", "20"))
SCHEDULE_WORKERS = max(1, min(4, int(os.environ.get("AUTO_SCHEDULE_WORKERS", "4"))))


def select_upcoming_targets(venue_ids, schedules, completed, now):
    targets = []
    for venue_id in venue_ids:
        for race, deadline in enumerate(schedules.get(venue_id, []), 1):
            if not deadline or (venue_id, race) in completed:
                continue
            try:
                deadline_at = datetime.combine(now.date(), datetime.strptime(deadline, "%H:%M").time(), JST)
            except ValueError:
                continue
            remaining = (deadline_at - now).total_seconds() / 60
            if MIN_REMAINING_MINUTES <= remaining <= LOOKAHEAD_MINUTES:
                targets.append((venue_id, race))
    return sorted(targets, key=lambda item: (int(item[0]), item[1]))


def fetch_schedule(venue_id, date):
    html = _fetch_html("/odds3t", {"jcd": venue_id, "hd": date, "rno": 1})
    soup = BeautifulSoup(html, "lxml")
    return [_parse_deadline(soup, race) for race in range(1, 13)]


def main():
    now = datetime.now(JST)
    if not PREDICTIONS.exists():
        raise SystemExit("predictions.json is missing")
    predictions = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    race_date = str(predictions.get("race_date") or "")
    if race_date != now.strftime("%Y-%m-%d"):
        raise SystemExit(f"prediction date is stale: {race_date}")
    venue_ids = [str(item["venue_id"]).zfill(2) for item in predictions.get("official_venues", [])]
    if not venue_ids:
        raise SystemExit("official venue list is empty")

    completed = set()
    if EXHIBITION.exists():
        exhibition = json.loads(EXHIBITION.read_text(encoding="utf-8"))
        if exhibition.get("race_date") == race_date:
            completed = {
                (str(item["venue_id"]).zfill(2), int(item["race"]))
                for item in exhibition.get("races", [])
                if item.get("status") == "FINAL" and int((item.get("value") or {}).get("portfolio_points") or 0) == 13
            }

    date = race_date.replace("-", "")
    schedules = {}
    with ThreadPoolExecutor(max_workers=SCHEDULE_WORKERS) as executor:
        futures = {executor.submit(fetch_schedule, venue_id, date): venue_id for venue_id in venue_ids}
        for future in as_completed(futures):
            venue_id = futures[future]
            try:
                schedules[venue_id] = future.result()
            except Exception as exc:
                print(f"schedule {venue_id}: {type(exc).__name__}")

    targets = select_upcoming_targets(venue_ids, schedules, completed, now)
    print(json.dumps({
        "checked_venues": len(schedules),
        "completed": len(completed),
        "targets": [f"{venue}-{race}" for venue, race in targets],
        "window_minutes": [MIN_REMAINING_MINUTES, LOOKAHEAD_MINUTES],
    }, ensure_ascii=False))
    if not targets:
        return
    os.environ["TARGET_RACES"] = ",".join(f"{venue}-{race}" for venue, race in targets)
    update_exhibition()


if __name__ == "__main__":
    main()
