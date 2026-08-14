from __future__ import annotations

import json
import math
import re
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PERFORMANCE = DATA / "performance.json"
HEADERS = {"User-Agent": "Mozilla/5.0 BETAKO-Free/1.0", "Accept-Language": "ja-JP,ja;q=0.9"}
EVALUATION_VERSION = "main6-v1"
VENUE_MIN_SAMPLES = 5
VENUE_MIN_HIT_RATE = 30.0
VENUE_MIN_NET_PROFIT = 0
VENUE_MIN_PROFIT_FACTOR = 1.2


def build_main_tickets(prediction: dict) -> list[str]:
    contender_boats = [str(item["boat"]) for item in prediction.get("contenders", [])]
    leading_boats = [boat for boat in str(prediction.get("pick", "")).split("-") if boat in contender_boats]
    boats = list(dict.fromkeys(leading_boats + contender_boats))
    if len(boats) < 4:
        return [prediction["pick"]] if prediction.get("pick") else []
    ticket = lambda first, second, third: f"{boats[first]}-{boats[second]}-{boats[third]}"
    return [
        ticket(0, 1, 2), ticket(0, 2, 1), ticket(0, 1, 3),
        ticket(0, 2, 3), ticket(0, 3, 1), ticket(0, 3, 2),
    ]


def fetch_result(date: str, venue_id: str, race: int):
    response = requests.get(
        "https://www.boatrace.jp/owpc/pc/race/raceresult",
        params={"hd": date, "jcd": venue_id, "rno": race},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    for tbody in soup.select("tbody"):
        cells = [cell.get_text(strip=True) for cell in tbody.select("td")]
        if cells and cells[0] == "3連単":
            combo_match = re.search(r"([1-6])-([1-6])-([1-6])", cells[1] if len(cells) > 1 else "")
            payout_match = re.search(r"([\d,]+)", cells[2] if len(cells) > 2 else "")
            if combo_match:
                return combo_match.group(0), int(payout_match.group(1).replace(",", "")) if payout_match else 0
    return None


def wilson_interval(hits: int, samples: int):
    if not samples:
        return None
    z = 1.959964
    p = hits / samples
    denominator = 1 + z * z / samples
    center = (p + z * z / (2 * samples)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * samples)) / samples) / denominator
    return [round(max(0, center - margin) * 100, 1), round(min(1, center + margin) * 100, 1)]


def summarize(records):
    ordered = sorted(records.values(), key=lambda item: item["key"])
    profits = [item["profit_yen"] for item in ordered]
    hits = sum(item["hit"] for item in ordered)
    gross_profit = sum(value for value in profits if value > 0)
    gross_loss = abs(sum(value for value in profits if value < 0))
    equity = peak = max_drawdown = 0
    for value in profits:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "samples": len(ordered),
        "hits": hits,
        "hit_rate": round(hits / len(ordered) * 100, 1) if ordered else 0,
        "hit_rate_ci95": wilson_interval(hits, len(ordered)),
        "net_profit_yen": sum(profits),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else ("∞" if gross_profit else 0),
        "max_drawdown_yen": max_drawdown,
    }


def build_daily_summaries(records, existing_daily=None):
    existing_daily = existing_daily or {}
    dates = set(existing_daily)
    for item in records.values():
        key = str(item.get("key", ""))
        if re.match(r"^\d{8}-", key):
            dates.add(key[:8])
    daily = {}
    for date in sorted(dates):
        day_records = {
            key: item for key, item in records.items()
            if str(item.get("key", key)).startswith(f"{date}-")
        }
        summary = summarize(day_records)
        previous = existing_daily.get(date, {})
        published = max(int(previous.get("published") or 0), summary["samples"])
        daily[date] = {
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "published": published,
            "evaluated": summary["samples"],
            "pending": max(0, published - summary["samples"]),
            **summary,
        }
    return daily


def score_tier(score, agreement=0):
    try:
        value = float(score)
        agreement_value = float(agreement or 0)
    except (TypeError, ValueError):
        return "unclassified"
    if value >= 75 and agreement_value >= 75:
        return "strict"
    if value >= 60:
        return "experimental"
    return "watch"


def build_today_venue_performance(date: str, history: dict, previous: dict | None = None):
    """Evaluate completed all-race predictions without mixing them into public top-3 stats."""
    previous = previous if previous and previous.get("race_date") == date else {}
    records = dict(previous.get("records") or {})
    predictions = [
        item for item in history.get("all_races", [])
        if float(item.get("data_rate") or 0) >= 100 and item.get("label") != "DATA BLOCKED"
    ]
    valid_keys = {f"{date}-{item['venue_id']}-{item['race']}" for item in predictions}
    records = {key: value for key, value in records.items() if key in valid_keys}

    for prediction in predictions:
        key = f"{date}-{prediction['venue_id']}-{prediction['race']}"
        if key in records:
            continue
        try:
            result = fetch_result(date, prediction["venue_id"], prediction["race"])
        except requests.RequestException as exc:
            print(f"{key}: {exc}")
            continue
        if not result:
            continue
        actual, payout = result
        tickets = build_main_tickets(prediction)
        stake = len(tickets) * 100
        hit = actual in tickets
        records[key] = {
            "key": key,
            "venue_id": prediction["venue_id"],
            "venue": prediction["venue"],
            "race": prediction["race"],
            "hit": hit,
            "actual": actual,
            "payout_yen": payout,
            "stake_yen": stake,
            "profit_yen": payout - stake if hit else -stake,
        }

    grouped = {}
    for record in records.values():
        grouped.setdefault(record["venue"], {})[record["key"]] = record
    venues = []
    for venue, venue_records in grouped.items():
        summary = summarize(venue_records)
        if summary["samples"] < VENUE_MIN_SAMPLES:
            status = "サンプル不足"
        elif (
            summary["hit_rate"] >= VENUE_MIN_HIT_RATE
            and summary["net_profit_yen"] > VENUE_MIN_NET_PROFIT
            and (summary["profit_factor"] == "∞" or float(summary["profit_factor"] or 0) >= VENUE_MIN_PROFIT_FACTOR)
        ):
            status = "好調"
        else:
            status = "WATCH"
        venues.append({
            "venue": venue,
            **summary,
            "status": status,
            "last_completed_race": max(item["race"] for item in venue_records.values()),
        })
    venues.sort(key=lambda item: (-item["hits"], -item["hit_rate"], -item["samples"], item["venue"]))
    return {
        "race_date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "basis": "当日朝に保存した全レース予想のうち公式結果確定済みレースのみ",
        "thresholds": {
            "minimum_samples": VENUE_MIN_SAMPLES,
            "minimum_hit_rate": VENUE_MIN_HIT_RATE,
            "minimum_net_profit_yen": VENUE_MIN_NET_PROFIT,
            "minimum_profit_factor": VENUE_MIN_PROFIT_FACTOR,
        },
        "records": records,
        "venues": venues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--today-venues", action="store_true", help="Update today's completed all-race venue summary")
    args = parser.parse_args()
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    history_file = DATA / "history" / f"{yesterday}.json"
    payload = json.loads(PERFORMANCE.read_text(encoding="utf-8")) if PERFORMANCE.exists() else {"evaluated": {}}
    records = payload.setdefault("evaluated", {})
    longshot_records = payload.setdefault("longshot_evaluated", {})
    existing_daily = payload.get("daily", {})
    if history_file.exists():
        history = json.loads(history_file.read_text(encoding="utf-8"))
        visible_predictions = history.get("rankings", [])[:3]
        existing_daily[yesterday] = {
            **existing_daily.get(yesterday, {}),
            "published": len(visible_predictions),
        }
        visible_keys = {
            f"{yesterday}-{prediction['venue_id']}-{prediction['race']}"
            for prediction in visible_predictions
        }
        for key in list(records):
            if key.startswith(f"{yesterday}-") and key not in visible_keys:
                records.pop(key)
        for prediction in visible_predictions:
            key = f"{yesterday}-{prediction['venue_id']}-{prediction['race']}"
            existing = records.get(key)
            if existing and existing.get("evaluation_version") == EVALUATION_VERSION:
                continue
            if existing and existing.get("actual"):
                actual, payout = existing["actual"], int(existing.get("payout_yen") or 0)
            else:
                try:
                    result = fetch_result(yesterday, prediction["venue_id"], prediction["race"])
                except requests.RequestException as exc:
                    print(f"{key}: {exc}")
                    continue
                if not result:
                    continue
                actual, payout = result
            tickets = build_main_tickets(prediction)
            stake = len(tickets) * 100
            hit = actual in tickets
            records[key] = {
                "key": key, "venue": prediction["venue"], "race": prediction["race"],
                "predicted": prediction["pick"], "predicted_tickets": tickets,
                "actual": actual, "hit": hit, "payout_yen": payout, "stake_yen": stake,
                "profit_yen": payout - stake if hit else -stake,
                "score": prediction.get("score"), "agreement": prediction.get("agreement"),
                "tier": score_tier(prediction.get("score"), prediction.get("agreement")),
                "evaluation_version": EVALUATION_VERSION,
            }
        for candidate in history.get("longshots", []):
            key = f"{yesterday}-{candidate['venue_id']}-{candidate['race']}-longshot"
            if key in longshot_records:
                continue
            try:
                result = fetch_result(yesterday, candidate["venue_id"], candidate["race"])
            except requests.RequestException as exc:
                print(f"{key}: {exc}")
                continue
            if not result:
                continue
            actual, payout = result
            formation = candidate.get("formation", "")
            prefix = formation.removesuffix("流し")
            hit = bool(prefix) and actual.startswith(prefix)
            stake = 400
            longshot_records[key] = {
                "key": key, "venue": candidate["venue"], "race": candidate["race"],
                "candidate_boat": candidate["boat"], "candidate_name": candidate["name"],
                "formation": formation, "actual": actual, "hit": hit,
                "payout_yen": payout, "stake_yen": stake,
                "profit_yen": payout - stake if hit else -stake,
            }
    if args.today_venues:
        today = datetime.now(JST).strftime("%Y%m%d")
        today_history_file = DATA / "history" / f"{today}.json"
        if today_history_file.exists():
            today_history = json.loads(today_history_file.read_text(encoding="utf-8"))
            payload["today_venue_performance"] = build_today_venue_performance(
                today, today_history, payload.get("today_venue_performance")
            )
    payload["updated_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    payload["summary"] = summarize(records)
    payload["tiers"] = {
        "strict": summarize({key: item for key, item in records.items() if item.get("tier") == "strict"}),
        "experimental": summarize({key: item for key, item in records.items() if item.get("tier") == "experimental"}),
    }
    payload["longshot_summary"] = summarize(longshot_records)
    payload["daily"] = build_daily_summaries(records, existing_daily)
    PERFORMANCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
