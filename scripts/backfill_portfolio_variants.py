from __future__ import annotations

import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from .evaluate_results import (
        PERFORMANCE,
        _portfolio_result_record,
        fetch_all_results,
        summarize,
    )
    from .update_exhibition import final_prediction, has_complete_portfolio
except ImportError:
    from evaluate_results import (
        PERFORMANCE,
        _portfolio_result_record,
        fetch_all_results,
        summarize,
    )
    from update_exhibition import final_prediction, has_complete_portfolio

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history"
BACKTEST = ROOT / "data" / "backtests" / "portfolio_variant_replay.json"
HIT_RATE_PRIORITY_TRIFECTA_MIN = 7.0


def hit_rate_priority_summary(records: dict) -> dict:
    probability_only = sorted(
        (item for item in records.values() if item.get("strategy") == "probability_only"),
        key=lambda item: item.get("key", ""),
    )

    def qualified(item):
        probabilities = [
            float(ticket.get("model_probability") or 0)
            for ticket in item.get("tickets", [])
            if ticket.get("bet_type") == "trifecta"
        ]
        return probabilities and max(probabilities) >= HIT_RATE_PRIORITY_TRIFECTA_MIN

    split = int(len(probability_only) * 0.7)
    training = {item["key"]: item for item in probability_only[:split] if qualified(item)}
    holdout = {item["key"]: item for item in probability_only[split:] if qualified(item)}
    combined = {**training, **holdout}
    return {
        "status": "CANDIDATE_ONLY",
        "threshold": {"top_trifecta_model_probability_min": HIT_RATE_PRIORITY_TRIFECTA_MIN},
        "overall": summarize(combined),
        "training_70pct": summarize(training),
        "holdout_30pct": summarize(holdout),
        "activation_rule": "holdout母数30件以上かつ改善を再確認するまで実戦ロジックへ自動反映しない",
    }


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8")


def current_fixed13_targets(performance: dict) -> set[tuple[str, str, int]]:
    targets = set()
    for record in (performance.get("portfolio_evaluated") or {}).values():
        key = str(record.get("key") or "")
        date = key[:8]
        venue_id = str(record.get("venue_id") or "").zfill(2)
        race = int(record.get("race") or 0)
        if len(date) == 8 and date.isdigit() and venue_id.isdigit() and 1 <= race <= 12:
            targets.add((date, venue_id, race))
    return targets


def load_prediction_lookup(date: str) -> dict[tuple[str, int], dict]:
    path = HISTORY / f"{date}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (str(item.get("venue_id") or "").zfill(2), int(item.get("race") or 0)): item
        for item in payload.get("all_races", [])
    }


def replay_probability_only(prediction: dict, race_item: dict) -> dict:
    replay = final_prediction(prediction, {
        "exhibition": race_item.get("exhibition") or [],
        "odds": None,
        "weather": race_item.get("weather"),
        "wind_speed": race_item.get("wind_speed"),
        "wave_height": race_item.get("wave_height"),
        "fetched_at": race_item.get("fetched_at"),
        "source_url": race_item.get("source_url"),
    })
    return replay.get("probability_only_portfolio") or {}


def collect_earliest_paired_snapshots(targets: set[tuple[str, str, int]]) -> dict:
    snapshots = {}
    prediction_cache = {}
    commits = git_text(
        "log", "--reverse", "--format=%H", "--", "data/exhibition.json"
    ).splitlines()
    for commit in commits:
        try:
            exhibition = json.loads(git_text("show", f"{commit}:data/exhibition.json"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        date = str(exhibition.get("race_date") or "").replace("-", "")
        date_targets = {target for target in targets if target[0] == date and target not in snapshots}
        if not date_targets:
            continue
        predictions = prediction_cache.setdefault(date, load_prediction_lookup(date))
        for race_item in exhibition.get("races", []):
            venue_id = str(race_item.get("venue_id") or "").zfill(2)
            race = int(race_item.get("race") or 0)
            target = (date, venue_id, race)
            if target not in date_targets:
                continue
            current = ((race_item.get("value") or {}).get("portfolio") or {})
            prediction = predictions.get((venue_id, race))
            if not prediction or not has_complete_portfolio(current):
                continue
            probability_only = replay_probability_only(prediction, race_item)
            if not has_complete_portfolio(probability_only):
                continue
            snapshots[target] = {
                "commit": commit,
                "snapshot_at": race_item.get("fetched_at") or exhibition.get("updated_at"),
                "race_item": race_item,
                "odds_aware": current,
                "probability_only": probability_only,
            }
    return snapshots


def paired_comparison(records: dict) -> dict:
    by_strategy = {}
    for strategy in ("odds_aware", "probability_only"):
        by_strategy[strategy] = {
            (str(item.get("key") or "")[:8], str(item.get("venue_id") or "").zfill(2), int(item.get("race") or 0)): item
            for item in records.values() if item.get("strategy") == strategy
        }
    paired_keys = set(by_strategy["odds_aware"]) & set(by_strategy["probability_only"])
    odds_only = sum(
        bool(by_strategy["odds_aware"][key]["hit"]) and not bool(by_strategy["probability_only"][key]["hit"])
        for key in paired_keys
    )
    probability_only = sum(
        bool(by_strategy["probability_only"][key]["hit"]) and not bool(by_strategy["odds_aware"][key]["hit"])
        for key in paired_keys
    )
    discordant = odds_only + probability_only
    tail = min(odds_only, probability_only)
    exact_p = min(1.0, 2 * sum(math.comb(discordant, i) for i in range(tail + 1)) / (2 ** discordant)) if discordant else 1.0
    return {
        "pairs": len(paired_keys),
        "both_hit": sum(
            bool(by_strategy["odds_aware"][key]["hit"]) and bool(by_strategy["probability_only"][key]["hit"])
            for key in paired_keys
        ),
        "odds_aware_only_hit": odds_only,
        "probability_only_hit": probability_only,
        "both_miss": sum(
            not bool(by_strategy["odds_aware"][key]["hit"]) and not bool(by_strategy["probability_only"][key]["hit"])
            for key in paired_keys
        ),
        "hit_rate_difference_points": round(
            (probability_only - odds_only) / len(paired_keys) * 100, 1
        ) if paired_keys else 0,
        "net_profit_difference_yen": sum(
            int(by_strategy["probability_only"][key]["profit_yen"])
            - int(by_strategy["odds_aware"][key]["profit_yen"])
            for key in paired_keys
        ),
        "mcnemar_exact_p": round(exact_p, 4),
        "statistically_significant_5pct": exact_p < 0.05,
    }


def main() -> None:
    performance = json.loads(PERFORMANCE.read_text(encoding="utf-8"))
    targets = current_fixed13_targets(performance)
    snapshots = collect_earliest_paired_snapshots(targets)
    stored = json.loads(BACKTEST.read_text(encoding="utf-8")) if BACKTEST.exists() else {}
    records = stored.get("evaluated") or performance.pop("portfolio_variant_backtest_evaluated", {})

    def needs_evaluation(target: tuple[str, str, int]) -> bool:
        date, venue_id, race = target
        return any(
            f"{date}-{venue_id}-{race}-{suffix}" not in records
            for suffix in ("backtest-odds-aware", "backtest-probability-only")
        )

    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_all_results, date, venue_id, race): target
            for target in snapshots for date, venue_id, race in [target]
            if needs_evaluation(target)
        }
        for future in as_completed(futures):
            target = futures[future]
            try:
                results[target] = future.result()
            except Exception as exc:  # Keep partial progress if an official page is unavailable.
                print(f"{target}: {exc}")

    for target, snapshot in snapshots.items():
        if not needs_evaluation(target):
            continue
        date, venue_id, race = target
        result = results.get(target)
        if not result:
            continue
        race_item = snapshot["race_item"]
        for strategy, portfolio, suffix in (
            ("odds_aware", snapshot["odds_aware"], "backtest-odds-aware"),
            ("probability_only", snapshot["probability_only"], "backtest-probability-only"),
        ):
            record = _portfolio_result_record(date, race_item, result, portfolio, strategy, suffix)
            if not record:
                continue
            record["validation_mode"] = "retrospective_replay"
            record["source_commit"] = snapshot["commit"]
            record["snapshot_at"] = snapshot["snapshot_at"]
            records[record["key"]] = record

    performance["portfolio_variant_backtest_summary"] = {
        strategy: summarize({key: item for key, item in records.items() if item.get("strategy") == strategy})
        for strategy in ("odds_aware", "probability_only")
    }
    performance["portfolio_variant_backtest_coverage"] = {
        "eligible_current_records": len(targets),
        "paired_snapshots": len(snapshots),
        "evaluated_pairs": min(
            performance["portfolio_variant_backtest_summary"]["odds_aware"]["samples"],
            performance["portfolio_variant_backtest_summary"]["probability_only"]["samples"],
        ),
        "method": "各レースで現行固定13点が最初に確定したGitスナップショットを、結果情報なしで再生",
        "odds_aware_source": "当時保存された現行固定13点",
        "probability_only_source": "同じ展示スナップショットをオッズなしで再予想",
    }
    performance["portfolio_variant_backtest_comparison"] = paired_comparison(records)
    performance["hit_rate_priority_backtest"] = hit_rate_priority_summary(records)
    BACKTEST.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST.write_text(json.dumps({
        "evaluation_version": "fixed13-retrospective-ab-v1",
        "coverage": performance["portfolio_variant_backtest_coverage"],
        "summary": performance["portfolio_variant_backtest_summary"],
        "comparison": performance["portfolio_variant_backtest_comparison"],
        "hit_rate_priority": performance["hit_rate_priority_backtest"],
        "evaluated": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PERFORMANCE.write_text(json.dumps(performance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(performance["portfolio_variant_backtest_summary"], ensure_ascii=False))
    print(json.dumps(performance["portfolio_variant_backtest_coverage"], ensure_ascii=False))
    print(json.dumps(performance["portfolio_variant_backtest_comparison"], ensure_ascii=False))


if __name__ == "__main__":
    main()
