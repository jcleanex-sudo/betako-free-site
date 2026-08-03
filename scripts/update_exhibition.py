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
    deadline = odds_payload.get("deadline")
    remaining_minutes = None
    if deadline:
        try:
            deadline_at = datetime.combine(datetime.now(JST).date(), datetime.strptime(deadline, "%H:%M").time(), JST)
            remaining_minutes = round((deadline_at - datetime.now(JST)).total_seconds() / 60, 1)
        except ValueError:
            deadline = None
    if not odds or model_probability is None:
        return {
            "status": "DATA BLOCKED", "odds": odds, "model_probability": model_probability,
            "market_probability": None, "net_edge": None,
            "deadline": deadline, "remaining_minutes": remaining_minutes,
            "message": "3連単オッズ未公開のため期待値判定なし",
            "source_url": odds_payload.get("source_url"),
        }

    if remaining_minutes is None:
        return {
            "status": "DATA BLOCKED", "odds": round(float(odds), 1),
            "model_probability": model_probability, "market_probability": round(100 / float(odds), 2),
            "net_edge": None, "deadline": deadline, "remaining_minutes": None,
            "message": "締切時刻を確認できないため見送り",
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
    if remaining_minutes < 5:
        status = "WATCH"
        message = "締切5分前を過ぎたため新規判定を停止"
    return {
        "status": status, "odds": round(float(odds), 1),
        "model_probability": round(model_probability, 2),
        "market_probability": round(market_probability, 2),
        "net_edge": round(net_edge, 2), "deadline": deadline,
        "remaining_minutes": remaining_minutes, "message": message,
        "source_url": odds_payload.get("source_url"),
    }


def longshot_judgement(prediction, realtime):
    candidate = prediction.get("longshot")
    if not candidate:
        return None
    axis = int(prediction["pick"].split("-")[0])
    hole = int(candidate["boat"])
    exhibition = next((item for item in realtime.get("exhibition", []) if item.get("boat") == hole), {})
    time_rank = exhibition.get("time_rank")
    odds_payload = realtime.get("odds") or {}
    deadline = odds_payload.get("deadline")
    remaining_minutes = None
    if deadline:
        try:
            deadline_at = datetime.combine(datetime.now(JST).date(), datetime.strptime(deadline, "%H:%M").time(), JST)
            remaining_minutes = round((deadline_at - datetime.now(JST)).total_seconds() / 60, 1)
        except ValueError:
            deadline = None

    base = {
        "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
        "boat": hole, "name": candidate["name"], "formation": candidate["formation"],
        "time_rank": time_rank, "deadline": deadline, "remaining_minutes": remaining_minutes,
    }
    if time_rank is None:
        return {**base, "status": "WAIT", "min_odds": None, "model_probability": None,
                "market_probability": None, "net_edge": None, "message": "候補艇の展示データ待ち"}

    odds = odds_payload.get("odds") or {}
    combinations = [f"{axis}-{hole}-{third}" for third in range(1, 7) if third not in (axis, hole)]
    formation_odds = [odds.get(combination) for combination in combinations]
    if remaining_minutes is None or any(value is None for value in formation_odds):
        return {**base, "status": "DATA BLOCKED", "min_odds": None, "model_probability": None,
                "market_probability": None, "net_edge": None, "message": "4点流しのオッズまたは締切時刻が未取得"}

    axis_probability = float(prediction.get("estimated_probability") or 0)
    hole_probability = float(candidate.get("relative_probability") or 0)
    model_probability = axis_probability / 100 * hole_probability / max(1, 100 - axis_probability) * 100
    min_odds = min(float(value) for value in formation_odds)
    market_probability = 400 / min_odds
    net_edge = model_probability - market_probability - 2.0
    status = "WATCH"
    message = "展示2位以内・net edge 5%以上の両条件を満たさないため見送り"
    if time_rank <= 2 and net_edge >= 5 and remaining_minutes >= 5:
        status = "UP"
        message = "展示・4点流しオッズ条件通過（仮想検証枠）"
    elif remaining_minutes < 5:
        message = "締切5分前を過ぎたため新規判定を停止"
    return {
        **base, "status": status, "min_odds": round(min_odds, 1),
        "model_probability": round(model_probability, 2),
        "market_probability": round(market_probability, 2), "net_edge": round(net_edge, 2),
        "message": message,
    }


def final_prediction(prediction, realtime):
    valid_times = [item for item in realtime.get("exhibition", []) if item.get("time") is not None]
    if len(valid_times) < 4:
        value = value_judgement(prediction.get("contenders", []), prediction["pick"], realtime)
        if value.get("status") == "UP":
            value["status"] = "WATCH"
            value["message"] = "期待値条件は通過したが展示不足のためUPを保留"
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
        if value.get("status") == "UP":
            value["status"] = "WATCH"
            value["message"] = "期待値条件は通過したが候補艇の展示不足のためUPを保留"
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
    longshots = []
    for prediction in payload.get("rankings", []):
        try:
            realtime = fetch_exhibition(prediction["venue_id"], prediction["race"], date)
            races.append(final_prediction(prediction, realtime))
            longshot = longshot_judgement(prediction, realtime)
            if longshot:
                longshots.append(longshot)
        except Exception as exc:
            races.append({
                "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
                "status": "DATA BLOCKED", "message": f"展示取得失敗: {type(exc).__name__}",
                "morning_pick": prediction["pick"],
            })
            if prediction.get("longshot"):
                longshots.append({
                    "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
                    "boat": prediction["longshot"]["boat"], "name": prediction["longshot"]["name"],
                    "formation": prediction["longshot"]["formation"], "status": "DATA BLOCKED",
                    "message": f"穴候補の直前情報取得失敗: {type(exc).__name__}",
                })
    output = {"updated_at": now.strftime("%Y-%m-%d %H:%M JST"), "races": races, "longshots": longshots}
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"races": len(races), "final": sum(item["status"] == "FINAL" for item in races)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
