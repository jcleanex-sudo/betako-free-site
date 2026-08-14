from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def fail(message: str) -> None:
    raise SystemExit(f"PUBLIC DATA VALIDATION FAILED: {message}")


def load(name: str) -> dict:
    path = DATA / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{name} cannot be read: {type(exc).__name__}")


def race_key(item: dict) -> tuple[str, int]:
    return str(item.get("venue_id", "")).zfill(2), int(item.get("race", 0))


def main() -> None:
    predictions = load("predictions.json")
    exhibition = load("exhibition.json")
    today = datetime.now(JST).strftime("%Y-%m-%d")

    if predictions.get("status") != "OK":
        fail("predictions status is not OK")
    if predictions.get("race_date") != today:
        fail(f"prediction date is {predictions.get('race_date')}, expected {today}")
    if exhibition.get("race_date") != today:
        fail(f"exhibition date is {exhibition.get('race_date')}, expected {today}")
    if exhibition.get("prediction_updated_at") != predictions.get("updated_at"):
        fail("prediction/exhibition dataset versions do not match")

    official = predictions.get("official_venues") or []
    venue_count = int(predictions.get("venue_count") or 0)
    expected = venue_count * 12
    races = predictions.get("all_races") or []
    exhibition_races = exhibition.get("races") or []
    if venue_count <= 0 or len(official) != venue_count:
        fail("official venue count is inconsistent")
    if int(predictions.get("expected_races") or 0) != expected:
        fail("expected race count is inconsistent")
    if len(races) != expected or int(predictions.get("fetched_races") or 0) != expected:
        fail(f"prediction races are incomplete: {len(races)}/{expected}")
    if len(exhibition_races) != expected:
        fail(f"exhibition races are incomplete: {len(exhibition_races)}/{expected}")

    prediction_keys = [race_key(item) for item in races]
    exhibition_keys = [race_key(item) for item in exhibition_races]
    if len(set(prediction_keys)) != expected:
        fail("prediction race keys contain duplicates")
    if len(set(exhibition_keys)) != expected:
        fail("exhibition race keys contain duplicates")
    if set(prediction_keys) != set(exhibition_keys):
        fail("prediction/exhibition race keys do not match")

    official_names = {str(item.get("venue_id", "")).zfill(2): item.get("venue") for item in official}
    for venue_id, venue_name in official_names.items():
        venue_races = [item for item in races if race_key(item)[0] == venue_id]
        if {int(item.get("race", 0)) for item in venue_races} != set(range(1, 13)):
            fail(f"{venue_name} does not contain exactly 1R-12R")
        if any(item.get("venue") != venue_name for item in venue_races):
            fail(f"venue id/name mismatch: {venue_id}")

    for item in races:
        contenders = item.get("contenders") or []
        if {int(row.get("boat", 0)) for row in contenders} != set(range(1, 7)):
            fail(f"prediction competitors incomplete: {race_key(item)}")

    race_lookup = {race_key(item): item for item in races}
    for item in predictions.get("rankings") or []:
        source = race_lookup.get(race_key(item))
        if not source or float(source.get("data_rate") or 0) < 100:
            fail(f"ranking contains incomplete data: {race_key(item)}")

    for item in exhibition_races:
        key = race_key(item)
        if item.get("venue") != official_names.get(key[0]):
            fail(f"exhibition venue mismatch: {key}")
        fetched_at = str(item.get("fetched_at") or "")
        if not fetched_at.startswith(today):
            fail(f"stale or missing exhibition timestamp: {key}")
        rows = item.get("exhibition") or []
        boats = [int(row.get("boat", 0)) for row in rows]
        if len(boats) != len(set(boats)) or any(boat not in range(1, 7) for boat in boats):
            fail(f"invalid exhibition boat rows: {key}")
        if item.get("status") == "FINAL":
            complete = {
                int(row.get("boat", 0)) for row in rows
                if row.get("time") is not None
                and row.get("course") in range(1, 7)
                and row.get("st") not in (None, "")
            }
            if complete != set(range(1, 7)):
                fail(f"FINAL without complete six-boat exhibition data: {key}")

    quality = {
        "status": "PASS",
        "race_date": today,
        "prediction_updated_at": predictions.get("updated_at"),
        "validated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "venue_count": venue_count,
        "race_count": expected,
        "final_count": sum(item.get("status") == "FINAL" for item in exhibition_races),
        "blocked_prediction_count": sum(float(item.get("data_rate") or 0) < 100 for item in races),
    }
    (DATA / "quality.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(quality, ensure_ascii=False))


if __name__ == "__main__":
    main()
