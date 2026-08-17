from __future__ import annotations

import json
import os
from itertools import permutations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fetch_race_realtime import fetch_exhibition

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "predictions.json"
OUTPUT = ROOT / "data" / "exhibition.json"
MAX_WORKERS = max(1, min(4, int(os.environ.get("BOATRACE_EXHIBITION_WORKERS", "4"))))

MARKET_LABELS = {
    "single": "単勝", "exacta": "2連単", "quinella": "2連複",
    "trio": "3連複", "trifecta": "3連単",
}
MARKET_RULES = {
    "single": {"margin": 2.0, "min_edge": 3.0, "min_probability": 25.0},
    "exacta": {"margin": 2.5, "min_edge": 5.0, "min_probability": 12.0},
    "quinella": {"margin": 2.0, "min_edge": 4.0, "min_probability": 22.0},
    "trio": {"margin": 2.5, "min_edge": 4.0, "min_probability": 15.0},
    "trifecta": {"margin": 3.0, "min_edge": 5.0, "min_probability": 5.0},
}


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


def ordered_finish_probability(contenders, boats):
    weights = {str(item["boat"]): max(0.1, float(item["relative_win_probability"])) for item in contenders}
    if not boats or any(boat not in weights for boat in boats) or len(set(boats)) != len(boats):
        return None
    remaining = sum(weights.values())
    probability = 1.0
    for boat in boats:
        probability *= weights[boat] / remaining
        remaining -= weights[boat]
    return probability * 100


def market_probability(contenders, market, pick):
    boats = str(pick).split("-")
    if market == "single":
        return ordered_finish_probability(contenders, boats)
    if market in ("exacta", "trifecta"):
        return ordered_finish_probability(contenders, boats)
    if market in ("quinella", "trio"):
        values = [ordered_finish_probability(contenders, order) for order in permutations(boats)]
        return sum(value for value in values if value is not None)
    return None


def remaining_minutes(odds_payload):
    deadline = odds_payload.get("deadline")
    if not deadline:
        return deadline, None
    try:
        deadline_at = datetime.combine(datetime.now(JST).date(), datetime.strptime(deadline, "%H:%M").time(), JST)
        return deadline, round((deadline_at - datetime.now(JST)).total_seconds() / 60, 1)
    except ValueError:
        return None, None


def compare_markets(contenders, realtime):
    payload = realtime.get("odds") or {}
    deadline, minutes = remaining_minutes(payload)
    markets = payload.get("markets") or {}
    if payload.get("status") != "OK" or set(markets) != set(MARKET_LABELS) or minutes is None:
        return {
            "status": "DATA BLOCKED", "bet_type": None, "bet_type_label": None,
            "pick": None, "odds": None, "model_probability": None,
            "market_probability": None, "net_edge": None, "expected_profit_yen": None,
            "deadline": deadline, "remaining_minutes": minutes,
            "message": "5券種の展示後オッズが100%揃っていないため予想停止",
            "ranking": [], "data_rate": 0,
        }

    rows = []
    for market, odds_map in markets.items():
        rule = MARKET_RULES[market]
        for pick, odds in odds_map.items():
            probability = market_probability(contenders, market, pick)
            if probability is None or not odds or odds <= 1:
                continue
            implied = 100 / float(odds)
            edge = probability - implied - rule["margin"]
            expected_profit = probability / 100 * float(odds) * 100 - 100
            qualifies = probability >= rule["min_probability"] and edge >= rule["min_edge"] and expected_profit > 0
            rows.append({
                "bet_type": market, "bet_type_label": MARKET_LABELS[market], "pick": pick,
                "odds": round(float(odds), 1), "model_probability": round(probability, 2),
                "market_probability": round(implied, 2), "net_edge": round(edge, 2),
                "expected_profit_yen": round(expected_profit), "qualifies": qualifies,
            })
    qualified = [row for row in rows if row["qualifies"]]
    qualified.sort(key=lambda row: (row["expected_profit_yen"], row["net_edge"], row["model_probability"]), reverse=True)
    fallback = sorted(rows, key=lambda row: (row["net_edge"], row["model_probability"]), reverse=True)
    best = (qualified or fallback or [None])[0]
    if not best:
        return {"status": "DATA BLOCKED", "message": "有効なオッズなし", "ranking": [], "data_rate": 100}
    status = "UP" if qualified and minutes >= 5 else "WATCH"
    message = "期待値・的中確率の両基準を通過" if status == "UP" else "期待値基準未満のため見送り"
    if minutes < 5:
        message = "締切5分前を過ぎたため新規判定を停止"
    return {
        **best, "status": status, "deadline": deadline, "remaining_minutes": minutes,
        "message": message, "ranking": (qualified or fallback)[:6], "data_rate": 100,
        "source_urls": payload.get("source_urls", {}),
    }


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


def ticket_plan(contenders, leading_pick, realtime):
    contender_boats = [str(item["boat"]) for item in contenders]
    leading_boats = [boat for boat in str(leading_pick).split("-") if boat in contender_boats]
    boats = list(dict.fromkeys(leading_boats + contender_boats))
    if len(boats) < 5:
        return {"main": [], "cover": [], "ranked_by_edge": False}

    patterns = [
        (0, 1, 2), (0, 2, 1), (0, 1, 3), (0, 2, 3), (0, 3, 1),
        (0, 3, 2), (1, 0, 2), (2, 0, 1), (1, 0, 3), (2, 0, 3),
        (0, 1, 4), (0, 2, 4),
    ]
    odds_map = ((realtime.get("odds") or {}).get("odds") or {})
    rows = []
    for first, second, third in patterns:
        pick = f"{boats[first]}-{boats[second]}-{boats[third]}"
        odds = odds_map.get(pick)
        model_probability = ordered_trifecta_probability(contenders, pick)
        market_probability = 100 / float(odds) if odds else None
        net_edge = model_probability - market_probability - 2.0 if market_probability is not None and model_probability is not None else None
        rows.append({
            "pick": pick,
            "odds": round(float(odds), 1) if odds else None,
            "model_probability": model_probability,
            "market_probability": round(market_probability, 2) if market_probability is not None else None,
            "net_edge": round(net_edge, 2) if net_edge is not None else None,
        })

    ranked_by_edge = all(item["net_edge"] is not None for item in rows)
    if ranked_by_edge:
        rows.sort(key=lambda item: item["net_edge"], reverse=True)
    return {"main": rows[:6], "cover": rows[6:12], "ranked_by_edge": ranked_by_edge}


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
    exhibition = realtime.get("exhibition", [])
    valid_times = [item for item in exhibition if item.get("time") is not None]
    complete_boats = {
        item.get("boat") for item in exhibition
        if item.get("boat") in range(1, 7)
        and item.get("time") is not None
        and item.get("course") in range(1, 7)
        and item.get("st") not in (None, "")
    }
    if complete_boats != set(range(1, 7)):
        plan = ticket_plan(prediction.get("contenders", []), prediction["pick"], realtime)
        value_pick = plan["main"][0]["pick"] if plan["main"] else prediction["pick"]
        value = value_judgement(prediction.get("contenders", []), value_pick, realtime)
        if value.get("status") == "UP":
            value["status"] = "WATCH"
            value["message"] = "期待値条件は通過したが展示不足のためUPを保留"
        return {
            "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
            "status": "WAIT", "message": "6艇の展示タイム・進入・STが揃うまで朝予想を維持", "morning_pick": prediction["pick"],
            "ticket_plan": plan, "best_value_pick": value_pick, "value": value,
            "exhibition": realtime.get("exhibition", []),
            "fetched_at": realtime.get("fetched_at"), "source_url": realtime.get("source_url"),
        }

    by_boat = {item["boat"]: item for item in realtime["exhibition"]}
    adjusted = []
    course_values = {1: 7.0, 2: 3.0, 3: 1.5, 4: 0.0, 5: -1.0, 6: -2.0}
    for contender in prediction.get("contenders", []):
        exhibition = by_boat.get(contender["boat"], {})
        time_rank = exhibition.get("time_rank") or 6
        st_rank = exhibition.get("st_rank") or 6
        actual_course = exhibition.get("course") or contender["boat"]
        course_adjustment = course_values.get(actual_course, 0) - course_values.get(contender["boat"], 0)
        adjusted_score = max(
            0.1,
            contender["relative_win_probability"]
            + (7 - time_rank) * 1.6
            + (7 - st_rank) * 0.8
            + course_adjustment,
        )
        adjusted.append((contender, adjusted_score, exhibition, course_adjustment))
    adjusted_total = sum(item[1] for item in adjusted) or 1
    adjusted = [
        ({**item[0], "relative_win_probability": round(item[1] / adjusted_total * 100, 2)}, item[1], item[2], item[3])
        for item in adjusted
    ]
    adjusted.sort(key=lambda item: item[1], reverse=True)
    if len(adjusted) < 3:
        plan = ticket_plan(prediction.get("contenders", []), prediction["pick"], realtime)
        value_pick = plan["main"][0]["pick"] if plan["main"] else prediction["pick"]
        value = value_judgement(prediction.get("contenders", []), value_pick, realtime)
        if value.get("status") == "UP":
            value["status"] = "WATCH"
            value["message"] = "期待値条件は通過したが候補艇の展示不足のためUPを保留"
        return {
            "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
            "status": "WAIT", "message": "候補艇の展示データ不足", "morning_pick": prediction["pick"],
            "ticket_plan": plan, "best_value_pick": value_pick, "value": value,
            "exhibition": realtime.get("exhibition", []),
            "fetched_at": realtime.get("fetched_at"), "source_url": realtime.get("source_url"),
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
        "朝の能力評価に展示順位・ST展示順位・実際の進入コースを加えて再計算",
    ]
    start_order = [item["boat"] for item in sorted(realtime["exhibition"], key=lambda item: item.get("course") or item["boat"])]
    if start_order != sorted(start_order):
        reasons.insert(1, f"進入変化 {'-'.join(map(str, start_order))}（前付け反映）")
    adjusted_contenders = [item[0] for item in adjusted]
    plan = ticket_plan(adjusted_contenders, final_pick, realtime)
    value = compare_markets(adjusted_contenders, realtime)
    value_pick = value.get("pick") or (plan["main"][0]["pick"] if plan["main"] else final_pick)
    return {
        "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
        "status": "FINAL", "message": "展示後再計算済み", "morning_pick": prediction["pick"],
        "final_pick": final_pick, "final_score": round(final_score, 1), "reasons": reasons,
        "ticket_plan": plan, "best_value_pick": value_pick,
        "market_comparison": value.get("ranking", []),
        "weather": realtime.get("weather"), "wind_speed": wind, "wave_height": wave,
        "start_order": start_order,
        "exhibition": realtime.get("exhibition", []),
        "value": value,
        "fetched_at": realtime.get("fetched_at"), "source_url": realtime.get("source_url"),
    }


def main():
    now = datetime.now(JST)
    if not PREDICTIONS.exists():
        raise SystemExit("predictions.json is missing")
    payload = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    race_date = payload.get("race_date") or now.strftime("%Y-%m-%d")
    date = race_date.replace("-", "")
    predictions = payload.get("all_races") or payload.get("rankings", [])
    target_venue = os.environ.get("TARGET_VENUE_ID", "").zfill(2)
    target_race_text = os.environ.get("TARGET_RACE", "")
    target_race = int(target_race_text) if target_race_text.isdigit() else None
    targeted = bool(target_venue and target_race)
    if targeted:
        predictions = [
            item for item in predictions
            if str(item["venue_id"]).zfill(2) == target_venue and int(item["race"]) == target_race
        ]
        if not predictions:
            raise SystemExit(f"target race not found: {target_venue}-{target_race}")

    def update_one(prediction):
        try:
            realtime = fetch_exhibition(prediction["venue_id"], prediction["race"], date)
            return final_prediction(prediction, realtime), longshot_judgement(prediction, realtime)
        except Exception as exc:
            race = {
                "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
                "status": "DATA BLOCKED", "message": f"展示取得失敗: {type(exc).__name__}",
                "morning_pick": prediction["pick"],
            }
            longshot = None
            if prediction.get("longshot"):
                longshot = {
                    "venue": prediction["venue"], "venue_id": prediction["venue_id"], "race": prediction["race"],
                    "boat": prediction["longshot"]["boat"], "name": prediction["longshot"]["name"],
                    "formation": prediction["longshot"]["formation"], "status": "DATA BLOCKED",
                    "message": f"穴候補の直前情報取得失敗: {type(exc).__name__}",
                }
            return race, longshot

    races = []
    longshots = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(update_one, prediction) for prediction in predictions]
        for future in as_completed(futures):
            race, longshot = future.result()
            races.append(race)
            if longshot:
                longshots.append(longshot)
    races.sort(key=lambda item: (int(item["venue_id"]), int(item["race"])))
    longshots.sort(key=lambda item: (int(item["venue_id"]), int(item["race"])))
    if targeted and OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if previous.get("race_date") == race_date:
            race_keys = {(str(item["venue_id"]).zfill(2), int(item["race"])) for item in races}
            longshot_keys = {(str(item["venue_id"]).zfill(2), int(item["race"])) for item in longshots}
            races.extend(
                item for item in previous.get("races", [])
                if (str(item["venue_id"]).zfill(2), int(item["race"])) not in race_keys
            )
            longshots.extend(
                item for item in previous.get("longshots", [])
                if (str(item["venue_id"]).zfill(2), int(item["race"])) not in longshot_keys
            )
        races.sort(key=lambda item: (int(item["venue_id"]), int(item["race"])))
        longshots.sort(key=lambda item: (int(item["venue_id"]), int(item["race"])))
    output = {
        "race_date": race_date,
        "updated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "update_mode": "selected_race" if targeted else "all_races",
        "races": races, "longshots": longshots,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "targets": len(predictions), "stored_races": len(races), "targeted": targeted,
        "final": sum(item["status"] == "FINAL" for item in races), "workers": MAX_WORKERS,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
