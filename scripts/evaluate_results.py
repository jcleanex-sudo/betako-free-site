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


def score_tier(score):
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unclassified"
    if value >= 70:
        return "strict"
    if value >= 60:
        return "experimental"
    return "watch"


def main():
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d")
    history_file = DATA / "history" / f"{yesterday}.json"
    payload = json.loads(PERFORMANCE.read_text(encoding="utf-8")) if PERFORMANCE.exists() else {"evaluated": {}}
    records = payload.setdefault("evaluated", {})
    if history_file.exists():
        history = json.loads(history_file.read_text(encoding="utf-8"))
        for prediction in history.get("rankings", []):
            key = f"{yesterday}-{prediction['venue_id']}-{prediction['race']}"
            if key in records:
                continue
            try:
                result = fetch_result(yesterday, prediction["venue_id"], prediction["race"])
            except requests.RequestException as exc:
                print(f"{key}: {exc}")
                continue
            if not result:
                continue
            actual, payout = result
            hit = prediction["pick"] == actual
            records[key] = {
                "key": key, "venue": prediction["venue"], "race": prediction["race"],
                "predicted": prediction["pick"], "actual": actual, "hit": hit,
                "payout_yen": payout, "profit_yen": payout - 100 if hit else -100,
                "score": prediction.get("score"), "tier": score_tier(prediction.get("score")),
            }
    payload["updated_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    payload["summary"] = summarize(records)
    payload["tiers"] = {
        "strict": summarize({key: item for key, item in records.items() if item.get("tier") == "strict"}),
        "experimental": summarize({key: item for key, item in records.items() if item.get("tier") == "experimental"}),
    }
    PERFORMANCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
