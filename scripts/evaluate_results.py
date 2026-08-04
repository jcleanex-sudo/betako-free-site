from __future__ import annotations

import json
import math
import re
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


def main():
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    history_file = DATA / "history" / f"{yesterday}.json"
    payload = json.loads(PERFORMANCE.read_text(encoding="utf-8")) if PERFORMANCE.exists() else {"evaluated": {}}
    records = payload.setdefault("evaluated", {})
    longshot_records = payload.setdefault("longshot_evaluated", {})
    if history_file.exists():
        history = json.loads(history_file.read_text(encoding="utf-8"))
        visible_predictions = history.get("rankings", [])[:3]
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
    payload["updated_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    payload["summary"] = summarize(records)
    payload["tiers"] = {
        "strict": summarize({key: item for key, item in records.items() if item.get("tier") == "strict"}),
        "experimental": summarize({key: item for key, item in records.items() if item.get("tier") == "experimental"}),
    }
    payload["longshot_summary"] = summarize(longshot_records)
    PERFORMANCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
