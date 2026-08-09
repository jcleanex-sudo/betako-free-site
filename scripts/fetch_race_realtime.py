#!/usr/bin/env python3
"""Fetch and evaluate BOATRACE realtime exhibition / before-race information."""

import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://www.boatrace.jp/owpc/pc/race"
JST = timezone(timedelta(hours=9))
REQUEST_TIMEOUT = int(os.environ.get(
    "BOATRACE_REALTIME_TIMEOUT",
    os.environ.get("BOATRACE_REQUEST_TIMEOUT", "20"),
))
REQUEST_RETRIES = int(os.environ.get("BOATRACE_REALTIME_RETRIES", "0"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Connection": "close",
}

STADIUM_NAMES = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}

WEATHER_MAP = {
    "1": "晴",
    "2": "曇り",
    "3": "雨",
    "4": "雪",
}

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=REQUEST_RETRIES,
    connect=REQUEST_RETRIES,
    read=REQUEST_RETRIES,
    backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
)))


def normalize_race_date(race_date):
    text = str(race_date or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", "")
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", text):
        return text.replace("/", "")
    try:
        return datetime.fromisoformat(text).strftime("%Y%m%d")
    except Exception:
        return text


def display_race_date(race_date):
    text = normalize_race_date(race_date)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return str(race_date or "")


def safe_float(value, default=None):
    try:
        text = str(value).strip().replace(",", "")
        text = text.replace("m", "").replace("cm", "").replace("kg", "")
        text = text.replace("F", "").replace("L", "")
        return float(text) if text else default
    except Exception:
        return default


def safe_int(value, default=None):
    try:
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else default
    except Exception:
        return default


def _fetch_html(path, params):
    url = f"{BASE_URL}{path}"
    response = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    expected_date = params.get("hd")
    if expected_date:
        expected_date = normalize_race_date(expected_date)
        final_query = urllib.parse.parse_qs(urllib.parse.urlparse(response.url).query)
        actual_date = (final_query.get("hd") or [expected_date])[0]
        if actual_date != expected_date:
            raise ValueError(f"BOATRACE response date mismatch: expected {expected_date}, got {actual_date}")
    return response.text


def _weather_from_soup(soup):
    info = {
        "weather": None,
        "wind_direction": None,
        "wind_speed": None,
        "wave_height": None,
        "temperature": None,
        "water_temperature": None,
    }

    weather_div = soup.find("div", class_="weather1")
    if weather_div:
        weather_icon = weather_div.select_one(".is-weather p")
        if weather_icon:
            for class_name in weather_icon.get("class") or []:
                match = re.search(r"is-weather(\d+)", class_name)
                if match:
                    info["weather"] = WEATHER_MAP.get(match.group(1))

        wind = weather_div.select_one(".is-wind .weather1_bodyUnitLabelData")
        if wind:
            info["wind_speed"] = safe_float(wind.get_text(" ", strip=True))

        wave = weather_div.select_one(".is-wave .weather1_bodyUnitLabelData")
        if wave:
            info["wave_height"] = safe_float(wave.get_text(" ", strip=True))

        wind_label = weather_div.select_one(".is-wind .weather1_bodyUnitLabelTitle")
        if wind_label:
            text = wind_label.get_text(" ", strip=True)
            if text and text != "風速":
                info["wind_direction"] = text

    page_text = soup.get_text(" ", strip=True)
    temp = re.search(r"気温\s*([\d.]+)", page_text)
    water = re.search(r"水温\s*([\d.]+)", page_text)
    if temp:
        info["temperature"] = safe_float(temp.group(1))
    if water:
        info["water_temperature"] = safe_float(water.group(1))

    return info


def _parse_exhibition_table(soup):
    exhibition = {}

    table = soup.find("table", class_="is-w748")
    if table:
        rows = table.find_all("tr")
        for row in rows:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            boat = safe_int(cells[0] if cells else None)
            if not boat or not (1 <= boat <= 6):
                continue

            # The official table columns are fixed: boat, photo, racer,
            # weight, exhibition time, tilt, ....  Do not scan every number
            # in the row: boat 6 itself otherwise looks like a 6.00 time.
            weight = safe_float(cells[3]) if len(cells) > 3 else None
            exhibition_time = safe_float(cells[4]) if len(cells) > 4 else None
            tilt = safe_float(cells[5]) if len(cells) > 5 else None
            if exhibition_time is not None and not (6.0 <= exhibition_time <= 7.5):
                exhibition_time = None
            if weight is not None and not (40.0 <= weight <= 70.0):
                weight = None
            if tilt is not None and not (-1.5 <= tilt <= 3.0):
                tilt = None

            exhibition[boat] = {
                "boat": boat,
                "time": exhibition_time,
                "tilt": tilt,
                "weight": weight,
                "st": None,
            }

    start_table = soup.find("table", class_="is-w238")
    if start_table:
        for start_item in start_table.select(".table1_boatImage1"):
            boat_span = start_item.select_one(".table1_boatImage1Number")
            time_span = start_item.select_one(".table1_boatImage1Time")
            boat = safe_int(boat_span.get_text(" ", strip=True)) if boat_span else None
            if not boat:
                continue
            st_text = time_span.get_text(" ", strip=True) if time_span else ""
            st_match = re.search(r"F?(?:\d+)?\.\d+", st_text)
            st = st_match.group(0) if st_match else None
            exhibition.setdefault(boat, {
                "boat": boat,
                "time": None,
                "tilt": None,
                "weight": None,
                "st": None,
            })
            exhibition[boat]["st"] = st

    return [exhibition[boat] for boat in sorted(exhibition)]


def trifecta_combinations_in_page_order():
    """Return the 120 combinations in the order used by the official odds table."""
    combinations = []
    for second_index in range(5):
        for third_index in range(4):
            for first in range(1, 7):
                remaining_for_second = [boat for boat in range(1, 7) if boat != first]
                second = remaining_for_second[second_index]
                remaining_for_third = [boat for boat in range(1, 7) if boat not in (first, second)]
                third = remaining_for_third[third_index]
                combinations.append(f"{first}-{second}-{third}")
    return combinations


def _parse_trifecta_odds(soup):
    points = soup.select(".oddsPoint")
    combinations = trifecta_combinations_in_page_order()
    if len(points) != len(combinations):
        return {}

    odds = {}
    for combination, point in zip(combinations, points):
        value = safe_float(point.get_text(" ", strip=True))
        if value is not None and value > 1:
            odds[combination] = value
    return odds


def _parse_deadline(soup, race_number):
    for row in soup.select("table tr"):
        text = row.get_text(" ", strip=True)
        if "締切予定時刻" not in text:
            continue
        times = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", text)
        if len(times) >= int(race_number):
            return times[int(race_number) - 1]
    return None


def fetch_trifecta_odds(stadium_id: str, race_number: int, race_date: str) -> dict:
    stadium_id = str(stadium_id).zfill(2)
    race_number = int(race_number)
    race_date_compact = normalize_race_date(race_date)
    params = {"jcd": stadium_id, "hd": race_date_compact, "rno": race_number}
    source_url = f"{BASE_URL}/odds3t?jcd={stadium_id}&hd={race_date_compact}&rno={race_number}"
    try:
        soup = BeautifulSoup(_fetch_html("/odds3t", params), "lxml")
        odds = _parse_trifecta_odds(soup)
        return {
            "status": "OK" if len(odds) == 120 else "DATA BLOCKED",
            "odds": odds,
            "deadline": _parse_deadline(soup, race_number),
            "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
            "source_url": source_url,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "DATA BLOCKED", "odds": {}, "deadline": None,
            "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
            "source_url": source_url, "error": str(exc),
        }


def evaluate_exhibition(realtime):
    exhibition = realtime.get("exhibition") or []
    valid_times = [item for item in exhibition if item.get("time") is not None]
    valid_st = [item for item in exhibition if item.get("st")]

    fastest = sorted(valid_times, key=lambda item: item["time"])
    st_rank = sorted(valid_st, key=lambda item: safe_float(item["st"].replace("F", ""), 99))

    comments = []
    if fastest:
        comments.append(f"展示最速は{fastest[0]['boat']}号艇 {fastest[0]['time']:.2f}。")
    if len(fastest) >= 2:
        comments.append(f"2番時計は{fastest[1]['boat']}号艇 {fastest[1]['time']:.2f}。")
    if st_rank:
        comments.append(f"ST展示トップは{st_rank[0]['boat']}号艇 {st_rank[0]['st']}。")

    wind_speed = realtime.get("wind_speed") or 0
    wave_height = realtime.get("wave_height") or 0
    if wind_speed >= 7 or wave_height >= 10:
        comments.append("風・波が強めで、インの信頼度は少し割り引き。")
    elif wind_speed or wave_height:
        comments.append(f"風{wind_speed:g}m・波{wave_height:g}cmで水面は大きく荒れていない読み。")

    return {
        "status": "ok" if exhibition else "unavailable",
        "fastest_boat": fastest[0]["boat"] if fastest else None,
        "fastest_time": fastest[0]["time"] if fastest else None,
        "second_boat": fastest[1]["boat"] if len(fastest) >= 2 else None,
        "second_time": fastest[1]["time"] if len(fastest) >= 2 else None,
        "st_top_boat": st_rank[0]["boat"] if st_rank else None,
        "st_top": st_rank[0]["st"] if st_rank else None,
        "comments": comments,
        "summary": " ".join(comments) if comments else "展示情報未取得",
    }


def add_exhibition_ranks(exhibition):
    time_ranked = sorted(
        [item for item in exhibition if item.get("time") is not None],
        key=lambda item: item["time"],
    )
    st_ranked = sorted(
        [item for item in exhibition if item.get("st")],
        key=lambda item: safe_float(str(item["st"]).replace("F", ""), 99),
    )
    for rank, item in enumerate(time_ranked, 1):
        item["time_rank"] = rank
    for rank, item in enumerate(st_ranked, 1):
        item["st_rank"] = rank
    for item in exhibition:
        item.setdefault("time_rank", None)
        item.setdefault("st_rank", None)
    return exhibition


def empty_realtime(stadium_id, race_number, race_date, error=None):
    return {
        "stadium_id": str(stadium_id).zfill(2),
        "stadium_name": STADIUM_NAMES.get(str(stadium_id).zfill(2), f"場{stadium_id}"),
        "race_number": int(race_number),
        "race_date": display_race_date(race_date),
        "weather": None,
        "wind_direction": None,
        "wind_speed": None,
        "wave_height": None,
        "temperature": None,
        "water_temperature": None,
        "odds": None,
        "exhibition": [],
        "evaluation": {"status": "unavailable", "summary": "展示情報未取得", "comments": []},
        "fetched_at": None,
        "source": "boatrace_beforeinfo",
        "source_url": None,
        "error": str(error) if error else None,
    }


def fetch_exhibition(stadium_id: str, race_number: int, race_date: str) -> dict:
    stadium_id = str(stadium_id).zfill(2)
    race_number = int(race_number)
    race_date_compact = normalize_race_date(race_date)
    params = {"jcd": stadium_id, "hd": race_date_compact, "rno": race_number}
    source_url = f"{BASE_URL}/beforeinfo?jcd={stadium_id}&hd={race_date_compact}&rno={race_number}"

    try:
        html = _fetch_html("/beforeinfo", params)
        soup = BeautifulSoup(html, "lxml")
        weather = _weather_from_soup(soup)
        exhibition = add_exhibition_ranks(_parse_exhibition_table(soup))
        # 展示がまだ公開されていないレースの120通りオッズ取得は省略する。
        # 全レース巡回時の公式サイト負荷を抑え、展示公開後だけ期待値を計算する。
        odds = fetch_trifecta_odds(stadium_id, race_number, race_date_compact) if len(exhibition) >= 4 else None
        realtime = {
            "stadium_id": stadium_id,
            "stadium_name": STADIUM_NAMES.get(stadium_id, f"場{stadium_id}"),
            "race_number": race_number,
            "race_date": display_race_date(race_date_compact),
            "weather": weather.get("weather"),
            "wind_direction": weather.get("wind_direction"),
            "wind_speed": weather.get("wind_speed"),
            "wave_height": weather.get("wave_height"),
            "temperature": weather.get("temperature"),
            "water_temperature": weather.get("water_temperature"),
            "odds": odds,
            "exhibition": exhibition,
            "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
            "source": "boatrace_beforeinfo",
            "source_url": source_url,
            "error": None,
        }
        realtime["evaluation"] = evaluate_exhibition(realtime)
        return realtime
    except Exception as exc:
        fallback = empty_realtime(stadium_id, race_number, race_date, error=exc)
        fallback["source_url"] = source_url
        return fallback


if __name__ == "__main__":
    import json
    import sys

    date_arg = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    stadium_arg = sys.argv[2] if len(sys.argv) > 2 else "24"
    race_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    print(json.dumps(fetch_exhibition(stadium_arg, race_arg, date_arg), ensure_ascii=False, indent=2))
