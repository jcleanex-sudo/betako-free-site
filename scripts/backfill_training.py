from __future__ import annotations

import argparse
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from generate_predictions import (
    CLASS_BONUS,
    COURSE_PRIOR,
    DEFAULT_MODEL_WEIGHTS,
    JST,
    MAX_WORKERS,
    ROOT,
    STADIUMS,
    discover_venues,
    fetch_race,
    load_model_weights,
    make_prediction,
    number,
    session,
)

TRAINING_DIR = ROOT / "data" / "training"
DATASET = TRAINING_DIR / "races.json"
MODEL_CONFIG = ROOT / "data" / "model_calibration.json"
MIN_ACTIVATION_SAMPLES = 800


def fetch_result_list(date: str, venue_id: str) -> dict[int, tuple[str, int]]:
    response = session().get(
        "https://www.boatrace.jp/owpc/pc/race/resultlist",
        params={"hd": date, "jcd": venue_id},
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    results: dict[int, tuple[str, int]] = {}
    for row in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if not cells:
            continue
        race_match = re.search(r"(?:^|\s)(1[0-2]|[1-9])R(?:\s|$)", cells[0])
        joined = " | ".join(cells)
        combo_match = re.search(r"([1-6])\s*-\s*([1-6])\s*-\s*([1-6])", joined)
        payout_match = re.search(r"[¥￥]\s*([\d,]+)", joined)
        if race_match and combo_match:
            race = int(race_match.group(1))
            combo = "-".join(combo_match.groups())
            payout = int(payout_match.group(1).replace(",", "")) if payout_match else 0
            results.setdefault(race, (combo, payout))
    return results


def compact_entries(entries: list[dict]) -> list[dict]:
    return [
        {
            "boat": item["boat"], "class": item["class"],
            "national": item.get("national"), "local": item.get("local"),
            "motor": item.get("motor"), "boat_rate": item.get("boat_rate"),
            "st": item.get("st"),
        }
        for item in entries
    ]


def collect_race(date: str, venue_id: str, race: int, actual: str, payout: int):
    time.sleep(0.12)
    entries = fetch_race(date, venue_id, race)
    if len(entries) != 6:
        return None
    prediction = make_prediction(venue_id, race, entries)
    if not prediction:
        return None
    return {
        "key": f"{date}-{venue_id}-{race}", "date": date,
        "venue_id": venue_id, "venue": STADIUMS[venue_id], "race": race,
        "entries": compact_entries(entries), "actual": actual, "winner": int(actual[0]),
        "payout_yen": payout, "baseline_pick": prediction["pick"],
        "baseline_score": prediction["score"], "data_rate": prediction["data_rate"],
    }


def load_records() -> dict[str, dict]:
    if not DATASET.exists():
        return {}
    try:
        payload = json.loads(DATASET.read_text(encoding="utf-8"))
        return {item["key"]: item for item in payload if item.get("key")}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_records(records: dict[str, dict]):
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records.values(), key=lambda item: item["key"])
    DATASET.write_text(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def target_dates(days: int, mode: str, records: dict[str, dict]) -> list[str]:
    yesterday = datetime.now(JST).date() - timedelta(days=1)
    if mode == "older" and records:
        earliest = min(datetime.strptime(item["date"], "%Y%m%d").date() for item in records.values())
        end = earliest - timedelta(days=1)
    else:
        end = yesterday
    return [(end - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]


def strength(entry: dict, weights: dict[str, float]) -> float:
    return (
        number(entry.get("national"), 4.5) * weights["national"]
        + number(entry.get("local"), 4.2) * weights["local"]
        + number(entry.get("motor"), 32.0) * weights["motor"]
        + number(entry.get("boat_rate"), 32.0) * weights["boat_rate"]
        + COURSE_PRIOR[int(entry["boat"])] * weights["course"]
        + CLASS_BONUS.get(entry.get("class"), -3.0) * weights["class"]
        + max(-4.0, min(5.0, (0.20 - number(entry.get("st"), 0.20)) * weights["st"]))
    )


def probabilities(record: dict, weights: dict[str, float]) -> dict[int, float]:
    scores = [(int(item["boat"]), strength(item, weights)) for item in record["entries"]]
    maximum = max(score for _, score in scores)
    temperature = max(4.0, float(weights["temperature"]))
    exp_scores = [(boat, math.exp((score - maximum) / temperature)) for boat, score in scores]
    total = sum(value for _, value in exp_scores)
    return {boat: value / total for boat, value in exp_scores}


def metrics(records: list[dict], weights: dict[str, float]) -> dict:
    if not records:
        return {"samples": 0, "log_loss": None, "top1_accuracy": None, "brier": None}
    log_loss = brier = 0.0
    hits = 0
    for record in records:
        probs = probabilities(record, weights)
        winner = int(record["winner"])
        probability = max(1e-9, probs.get(winner, 1e-9))
        log_loss -= math.log(probability)
        predicted = max(probs, key=probs.get)
        hits += predicted == winner
        brier += sum((value - (1.0 if boat == winner else 0.0)) ** 2 for boat, value in probs.items())
    size = len(records)
    return {
        "samples": size, "log_loss": round(log_loss / size, 5),
        "top1_accuracy": round(hits / size * 100, 2), "brier": round(brier / size, 5),
    }


def objective(records: list[dict], weights: dict[str, float], anchor: dict[str, float]) -> float:
    result = metrics(records, weights)
    penalty = 0.004 * sum(
        math.log(max(1e-6, weights[key]) / max(1e-6, anchor[key])) ** 2
        for key in weights
    )
    return float(result["log_loss"]) + penalty


def tune(train: list[dict], initial: dict[str, float]) -> dict[str, float]:
    candidate = initial.copy()
    for _ in range(2):
        for key in candidate:
            center = candidate[key]
            choices = [center * 0.82, center, center * 1.18]
            if key == "temperature":
                choices = [max(4.0, value) for value in choices]
            best = min(
                ({**candidate, key: value} for value in choices),
                key=lambda weights: objective(train, weights, initial),
            )
            candidate = best
    return {key: round(value, 5) for key, value in candidate.items()}


def calibrate(records: dict[str, dict]):
    ordered = sorted(records.values(), key=lambda item: item["key"])
    current = load_model_weights()
    split_index = max(1, int(len(ordered) * 0.8))
    train, validation = ordered[:split_index], ordered[split_index:]
    baseline_validation = metrics(validation, current)
    status = "COLLECTING"
    candidate = current.copy()
    candidate_validation = baseline_validation
    activated = False
    reason = f"安全な自動調整には最低{MIN_ACTIVATION_SAMPLES}レース必要"

    if len(ordered) >= MIN_ACTIVATION_SAMPLES and len(validation) >= 100:
        candidate = tune(train, current)
        candidate_validation = metrics(validation, candidate)
        loss_gain = baseline_validation["log_loss"] - candidate_validation["log_loss"]
        accuracy_ok = candidate_validation["top1_accuracy"] >= baseline_validation["top1_accuracy"] - 0.5
        if loss_gain >= 0.003 and accuracy_ok:
            status = "ACTIVATED"
            activated = True
            reason = f"時系列検証log lossを{loss_gain:.4f}改善"
        else:
            status = "RETAINED"
            reason = "時系列検証で改善基準を満たさないため旧ロジックを維持"

    active = candidate if activated else current
    output = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "status": status, "reason": reason, "samples": len(ordered),
        "date_range": [ordered[0]["date"], ordered[-1]["date"]] if ordered else None,
        "minimum_activation_samples": MIN_ACTIVATION_SAMPLES,
        "train_samples": len(train), "validation_samples": len(validation),
        "baseline_validation": baseline_validation,
        "candidate_validation": candidate_validation,
        "active_weights": active, "candidate_weights": candidate,
        "logic_transition": "v3 → v4 historical calibration" if activated else "変更なし",
        "source": "BOAT RACE公式 出走表・結果一覧",
    }
    MODEL_CONFIG.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description="Backfill official historical races and calibrate BETAKO")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--mode", choices=("recent", "older"), default="older")
    args = parser.parse_args()
    days = max(1, min(14, args.days))
    records = load_records()

    for date in target_dates(days, args.mode, records):
        try:
            venues = discover_venues(date)
        except requests.RequestException as exc:
            print(f"{date}: venue discovery failed: {exc}")
            continue
        tasks = []
        for venue_id in venues:
            try:
                results = fetch_result_list(date, venue_id)
            except requests.RequestException as exc:
                print(f"{date}-{venue_id}: result list failed: {exc}")
                continue
            for race, (actual, payout) in results.items():
                key = f"{date}-{venue_id}-{race}"
                if key not in records:
                    tasks.append((venue_id, race, actual, payout))

        added = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(collect_race, date, venue, race, actual, payout): (venue, race)
                for venue, race, actual, payout in tasks
            }
            for future in as_completed(futures):
                venue, race = futures[future]
                try:
                    record = future.result()
                except requests.RequestException as exc:
                    print(f"{date}-{venue}-{race}: race fetch failed: {exc}")
                    continue
                if record:
                    records[record["key"]] = record
                    added += 1
        save_records(records)
        print(json.dumps({"date": date, "venues": len(venues), "added": added, "total": len(records)}, ensure_ascii=False))

    calibration = calibrate(records)
    print(json.dumps({
        "status": calibration["status"], "samples": calibration["samples"],
        "validation": calibration["candidate_validation"], "reason": calibration["reason"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
