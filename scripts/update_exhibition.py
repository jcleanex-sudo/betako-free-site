from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fetch_race_realtime import fetch_exhibition

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "predictions.json"
OUTPUT = ROOT / "data" / "exhibition.json"


def ordered_trifecta_probability(contenders, pick):
    """Conservative Plackett-Luce approximation for one exact trifecta."""
    weights = {str(item["boat"]): max(0.1, float(item["relative_win_probability"])) for item in contenders}
    boats = pick.split("-")
    if len(boats) != 3 or any(boat not in weights for boat in boats):
        return None
    remaining_total = 100.0
    probability = 1.0
    for boat in boats:
        weight = min(weights[boat], remaining_total)
        probability *= weight / remaining_total
        remaining_total -= weight
        if remaining_total <= 0:
            break
    return round(max(0.0, min(1.0, probability)) * 100, 2)


def value_judgement(contenders, pick, realtime):
    odds_payload = realtime.get("odds") or {}
    odds = (odds_payload.get("odds") or {}).get(pick)
    model_probability = ordered_trifecta_probability(contenders, pick)
    if not odds or model_probability is None:
        return {
            "status": "DATA BLOCKED", "odds": odds, "model_probability": model_probability,
            "market_probability": None, "net_edge": None,
            "message": "3連単オッズ未公開のため期待値判定なし",
            "source_url": odds_payload.get("source_url"),
        }

    market_probability = 100 / float(odds)
    # 直前変動・モデル誤差の安全余白として2ポイントを控除する。
    net_edge = model_probability - market_probability - 2.0
    status = "WATCH"
    message = "安全余白控除後の優位性が基準未満のため見送り"
    if net_edge >= 5:
        status = "UP"
        message = "検証用候補（実購入を推奨するものではありません）"
    return {
        "status": status, "odds": round(float(odds), 1),
        "model_probability": round(model_probability, 2),
        "market_probability": round(market_probability, 2),
        "net_edge": round(net_edge, 2), "message": message,
        "source_url": odds_payload.get("source_url"),
    }


def final_prediction(prediction, realtime):
    valid_times = [item for item in realtime.get("exhibition", []) if item.get("time") is not None]
    if len(valid_times) < 4:
        value = value_judgement(prediction.get("contenders", []), prediction["pick"], realtime)
        return {
            "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
            "status": "WAIT", "message": "展示データ不足のため朝予想を維持", "morning_pick": prediction["pick"],
            "value": value,
            "source_url": realtime.get("source_url"),
        }

    by_boat = {item["boat"]: item for item in realtime["exhibition"]}
    adjusted = []
    for contender in prediction.get("contenders", []):
        exhibition = by_boat.get(contender["boat"], {})
        time_rank = exhibition.get("time_rank") or 6
        st_rank = exhibition.get("st_rank") or 6
        adjusted_score = contender["relative_win_probability"] + (7 - time_rank) * 1.6 + (7 - st_rank) * 0.8
        adjusted.append((contender, adjusted_score, exhibition))
    adjusted.sort(key=lambda item: item[1], reverse=True)
    if len(adjusted) < 3:
        value = value_judgement(prediction.get("contenders", []), prediction["pick"], realtime)
        return {
            "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
            "status": "WAIT", "message": "候補艇の展示データ不足", "morning_pick": prediction["pick"],
            "value": value,
            "source_url": realtime.get("source_url"),
        }

    final_pick = "-".join(str(item[0]["boat"]) for item in adjusted[:3])
    fastest = min(valid_times, key=lambda item: item["time"])
    wind = realtime.get("wind_speed") or 0
    wave = realtime.get("wave_height") or 0
    risk_penalty = 4 if wind >= 7 or wave >= 10 else 0
    same_axis = str(adjusted[0][0]["boat"]) == prediction["pick"].split("-")[0]
    final_score = max(0, min(90, prediction["score"] + (2 if same_axis else -3) - risk_penalty))
    reasons = [
        f"展示最速は{fastest['boat']}号艇 {fastest['time']:.2f}",
        f"風速{wind:g}m・波高{wave:g}cm・天候{realtime.get('weather') or '不明'}",
        "朝の能力評価に展示順位とST展示順位を加えて再計算",
    ]
    value = value_judgement([item[0] for item in adjusted], final_pick, realtime)
    return {
        "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
        "status": "FINAL", "message": "展示後再計算済み", "morning_pick": prediction["pick"],
        "final_pick": final_pick, "final_score": round(final_score, 1), "reasons": reasons,
        "weather": realtime.get("weather"), "wind_speed": wind, "wave_height": wave,
        "value": value,
        "fetched_at": realtime.get("fetched_at"), "source_url": realtime.get("source_url"),
    }


def main():
    now = datetime.now(JST)
    if not PREDICTIONS.exists():
        raise SystemExit("predictions.json is missing")
    payload = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    date = now.strftime("%Y%m%d")
    races = []
    for prediction in payload.get("rankings", []):
        try:
            realtime = fetch_exhibition(prediction["venue_id"], prediction["race"], date)
            races.append(final_prediction(prediction, realtime))
        except Exception as exc:
            races.append({
                "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
                "status": "DATA BLOCKED", "message": f"展示取得失敗: {type(exc).__name__}",
                "morning_pick": prediction["pick"],
            })
    output = {"updated_at": now.strftime("%Y-%m-%d %H:%M JST"), "races": races}
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"races": len(races), "final": sum(item["status"] == "FINAL" for item in races)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
