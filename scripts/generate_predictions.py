from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
BASE = "https://www.boatrace.jp/owpc/pc/race"
STADIUMS = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
COURSE_PRIOR = {1: 1.00, 2: 0.43, 3: 0.36, 4: 0.32, 5: 0.22, 6: 0.15}
CLASS_BONUS = {"A1": 12.0, "A2": 7.0, "B1": 2.0, "B2": -3.0}
HEADERS = {"User-Agent": "Mozilla/5.0 BETAKO-Free/1.0", "Accept-Language": "ja-JP,ja;q=0.9"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def discover_venues(date: str) -> list[str]:
    response = SESSION.get(f"{BASE}/index", params={"hd": date}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    found = []
    for anchor in soup.select('a[href*="jcd="]'):
        query = parse_qs(urlparse(anchor.get("href", "")).query)
        venue = (query.get("jcd") or [""])[0].zfill(2)
        if venue in STADIUMS and venue not in found:
            found.append(venue)
    return found


def parse_entry(tbody, stadium_id: str):
    rows = tbody.find_all("tr")
    if not rows:
        return None
    cells = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["td", "th"])]
    boat_map = {"１":1,"２":2,"３":3,"４":4,"５":5,"６":6}
    if not cells or cells[0] not in boat_map:
        return None
    boat = boat_map[cells[0]]
    racer_link = tbody.select_one('a[href*="toban="]')
    racer_cell = cells[2] if len(cells) > 2 else ""
    racer_link_text = " ".join(racer_link.stripped_strings) if racer_link else ""
    source = racer_link_text or racer_cell
    racer_class = next((value for value in ("A1", "A2", "B1", "B2") if value in source), "B2")
    name_node = racer_link.select_one(".is-fs18") if racer_link else None
    racer_name = name_node.get_text(" ", strip=True) if name_node else ""
    if not racer_name and racer_link:
        for part in racer_link.stripped_strings:
            candidate = re.sub(r"\s+", " ", str(part)).strip()
            if (
                re.search(r"[一-龯々〆ヵヶぁ-んァ-ヶ]", candidate)
                and "/" not in candidate
                and not re.fullmatch(r"(?:A1|A2|B1|B2|\d{4}|\d+歳|[\d.]+kg)", candidate)
            ):
                racer_name = candidate
                break
    if not racer_name:
        name_match = re.search(r"\d{4}\s*/\s*(?:A1|A2|B1|B2)\s+(.+?)\s+[^\s/]+/[^\s/]+", source)
        racer_name = name_match.group(1).strip() if name_match else f"{boat}号艇"
    racer_name = re.sub(r"[\s　]+", " ", racer_name).strip()

    def floats(index):
        return [number(value) for value in re.findall(r"\d+\.\d+", cells[index] if len(cells) > index else "")]

    national, local, motor, boat_stats = floats(4), floats(5), floats(6), floats(7)
    st_match = re.search(r"(\d+\.\d+)$", cells[3] if len(cells) > 3 else "")
    return {
        "boat": boat,
        "name": racer_name,
        "class": racer_class,
        "national": national[0] if national else None,
        "local": local[0] if local else None,
        "motor": motor[0] if motor else None,
        "boat_rate": boat_stats[0] if boat_stats else None,
        "st": number(st_match.group(1), 0.20) if st_match else None,
        "stadium": stadium_id,
    }


def fetch_race(date: str, stadium_id: str, race: int):
    response = SESSION.get(f"{BASE}/racelist", params={"jcd": stadium_id, "hd": date, "rno": race}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    entries = [parse_entry(tbody, stadium_id) for tbody in soup.find_all("tbody", class_="is-fs12")]
    return [entry for entry in entries if entry]


def make_prediction(stadium_id: str, race: int, entries: list[dict]):
    if len(entries) != 6:
        return None
    scored = []
    completeness = []
    for entry in entries:
        available = sum(entry[key] is not None for key in ("national", "local", "motor", "boat_rate", "st"))
        completeness.append(available / 5)
        strength = (
            number(entry["national"], 4.5) * 7.5
            + number(entry["local"], 4.2) * 4.0
            + number(entry["motor"], 32.0) * 0.28
            + number(entry["boat_rate"], 32.0) * 0.10
            + COURSE_PRIOR[entry["boat"]] * 24.0
            + CLASS_BONUS[entry["class"]]
            + max(-4.0, min(5.0, (0.20 - number(entry["st"], 0.20)) * 80.0))
        )
        scored.append((entry, strength))
    maximum = max(score for _, score in scored)
    weights = [(entry, math.exp((score - maximum) / 12.0)) for entry, score in scored]
    total = sum(weight for _, weight in weights)
    ranked = sorted(((entry, weight / total) for entry, weight in weights), key=lambda item: item[1], reverse=True)
    top_boat = ranked[0][0]["boat"]
    factor_winners = [
        max(entries, key=lambda e: number(e["national"], 0))["boat"],
        max(entries, key=lambda e: number(e["local"], 0))["boat"],
        max(entries, key=lambda e: number(e["motor"], 0))["boat"],
        min(entries, key=lambda e: number(e["st"], 9))["boat"],
    ]
    agreement = factor_winners.count(top_boat) / len(factor_winners) * 100
    data_rate = sum(completeness) / len(completeness) * 100
    top_probability = ranked[0][1]
    score = min(90.0, 25.0 + top_probability * 45.0 + agreement * 0.15 + data_rate * 0.03)
    label = "厳格候補" if score >= 70 else "検証候補" if score >= 60 else "見送り"
    top_entry = ranked[0][0]
    top_factor_count = factor_winners.count(top_boat)
    contenders = [
        {
            "boat": entry["boat"],
            "name": entry["name"],
            "class": entry["class"],
            "relative_win_probability": round(probability * 100, 1),
            "national_win_rate": entry["national"],
            "local_win_rate": entry["local"],
            "motor_2rate": entry["motor"],
            "avg_st": entry["st"],
        }
        for entry, probability in ranked
    ]
    reasons = [
        f"{top_boat}号艇 {top_entry['name']}（{top_entry['class']}）を1着軸に評価",
        f"全国勝率 {number(top_entry['national'], 0):.2f}・当地勝率 {number(top_entry['local'], 0):.2f}・モーター2連率 {number(top_entry['motor'], 0):.1f}%",
        f"能力・当地・モーター・STの4因子中 {top_factor_count}因子が軸艇と一致",
    ]
    invalid_conditions = [
        "展示タイム・進入・欠場に大きな変化が出た場合",
        "強風・高波など朝データ取得後に水面条件が急変した場合",
        "データ取得率が90%未満または公式情報を再取得できない場合",
    ]
    longshot = None
    longshot_pool = []
    for entry, probability in ranked[1:]:
        probability_pct = probability * 100
        motor = number(entry["motor"], 0)
        local = number(entry["local"], 0)
        national = number(entry["national"], 0)
        st = number(entry["st"], 0.20)
        signals = sum((motor >= 35, local >= 5.5, national >= 5.5, st <= 0.16))
        if probability_pct <= 25 and signals:
            upside = (
                max(0, motor - 32) * 0.55
                + max(0, local - 5) * 2.2
                + max(0, national - 5) * 2.0
                + max(0, 0.18 - st) * 60
                + (3 if entry["boat"] >= 4 else 0)
            )
            hole_index = min(79.0, 35 + probability_pct * 0.8 + upside)
            longshot_pool.append((entry, probability_pct, hole_index, signals))
    if longshot_pool:
        entry, probability_pct, hole_index, signals = max(longshot_pool, key=lambda item: item[2])
        longshot = {
            "boat": entry["boat"], "name": entry["name"], "class": entry["class"],
            "hole_index": round(hole_index, 1), "status": "WATCH",
            "relative_probability": round(probability_pct, 1),
            "formation": f"{top_boat}-{entry['boat']}-流し",
            "reasons": [
                f"相対モデル確率 {probability_pct:.1f}%の人気薄候補",
                f"当地勝率 {number(entry['local'], 0):.2f}・モーター2連率 {number(entry['motor'], 0):.1f}%・平均ST {number(entry['st'], 0.20):.2f}",
                f"穴評価4因子のうち {signals}因子が基準を通過",
            ],
            "condition": "展示順位上位かつ3連単オッズ公開後に期待値を再確認",
        }
    return {
        "venue_id": stadium_id,
        "venue": STADIUMS[stadium_id],
        "race": race,
        "score": round(score, 1),
        "label": label,
        "pick": "-".join(str(entry["boat"]) for entry, _ in ranked[:3]),
        "agreement": round(agreement, 1),
        "data_rate": round(data_rate, 1),
        "estimated_probability": round(top_probability * 100, 1),
        "generation_mode": "公開用複合因子ロジック v3",
        "logic": "基礎能力・当地適性・モーター・ST・コース補正",
        "contenders": contenders,
        "reasons": reasons,
        "invalid_conditions": invalid_conditions,
        "longshot": longshot,
    }


def main():
    now = datetime.now(JST)
    date = now.strftime("%Y%m%d")
    output = {"status": "DATA BLOCKED", "updated_at": now.strftime("%Y-%m-%d %H:%M JST"), "message": "公式データ不足", "rankings": [], "longshots": []}
    try:
        venues = discover_venues(date)
        predictions = []
        for stadium_id in venues:
            for race in (6, 8, 10):
                try:
                    prediction = make_prediction(stadium_id, race, fetch_race(date, stadium_id, race))
                    if prediction:
                        predictions.append(prediction)
                except requests.RequestException as exc:
                    print(f"{STADIUMS[stadium_id]} {race}R: {exc}")
        eligible = [
            prediction for prediction in predictions
            if prediction["score"] >= 60 and prediction["data_rate"] >= 95
        ]
        eligible.sort(key=lambda item: (item["score"], item["agreement"], item["data_rate"]), reverse=True)
        if eligible:
            selected = eligible[:8]
            longshots = [
                {
                    "venue_id": prediction["venue_id"], "venue": prediction["venue"],
                    "race": prediction["race"], "main_pick": prediction["pick"],
                    **prediction["longshot"],
                }
                for prediction in selected if prediction.get("longshot")
            ]
            longshots.sort(key=lambda item: item["hole_index"], reverse=True)
            output.update(
                status="OK",
                message="6R・8R・10Rを全比較し、データ取得率95%以上から自動選抜",
                rankings=selected,
                longshots=longshots[:3],
                selection_policy="score>=60, data_rate>=95, compare=6R/8R/10R",
            )
        else:
            output["message"] = "品質基準を満たす候補がないため全レース見送り"
    except Exception as exc:
        output["message"] = f"データ更新失敗: {type(exc).__name__}"
        print(exc)
    target = Path(__file__).resolve().parents[1] / "data" / "predictions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history = target.parent / "history" / f"{date}.json"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "count": len(output["rankings"]), "target": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
