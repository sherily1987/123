#!/usr/bin/env python3
"""Time-split calibration research for the nine-state half/full market.

Uses only historical Football-Data results and their documented closing 1X2
odds to reconstruct the same market-derived lambdas used by the engine.  The
result is a research artifact: international closing odds never enter the
Sporttery production route or any current prediction.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
CORE = WORKSPACE / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
SOURCE = WORKSPACE / "project003_五大联赛数据下载" / "04_素材" / "football-data_match_csv"
OUT = HERE.parent / "05_交付" / "半全场校准"
STATES = ("HH", "HD", "HA", "DH", "DD", "DA", "AH", "AD", "AA")
TEMPERATURE_GRID = (0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40)
MIN_TEST_N = 1000
MIN_LOGLOSS_GAIN = 0.003

LEAGUES = {
    "eng_premier_league": "E0",
    "esp_la_liga": "SP1",
    "ger_bundesliga": "D1",
    "ita_serie_a": "I1",
    "fra_ligue_1": "F1",
}


def _result(h: int, a: int) -> str:
    return "H" if h > a else ("A" if h < a else "D")


def hafu_label(ht_home: int, ht_away: int, ft_home: int, ft_away: int) -> str:
    return _result(ht_home, ht_away) + _result(ft_home, ft_away)


def temperature_scale(probs: Iterable[float], temperature: float) -> list[float]:
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    raw = [max(float(value), 1e-15) ** (1.0 / temperature) for value in probs]
    total = sum(raw)
    return [value / total for value in raw]


def metrics(rows: Iterable[dict[str, Any]], temperature: float = 1.0) -> dict[str, float | int | None]:
    log_losses: list[float] = []
    briers: list[float] = []
    hits = 0
    for row in rows:
        probs = temperature_scale(row["raw_probs"], temperature)
        actual = int(row["actual_idx"])
        log_losses.append(-math.log(max(probs[actual], 1e-15)))
        briers.append(sum((p - int(index == actual)) ** 2 for index, p in enumerate(probs)))
        hits += int(max(range(len(probs)), key=probs.__getitem__) == actual)
    n = len(log_losses)
    return {"n": n, "log_loss": round(sum(log_losses) / n, 6) if n else None,
            "brier": round(sum(briers) / n, 6) if n else None,
            "accuracy_pct": round(100.0 * hits / n, 2) if n else None}


def _number(row: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        try:
            value = float(str(row.get(key) or "").strip())
        except ValueError:
            continue
        if math.isfinite(value) and value > 1.0:
            return value
    return None


def _season_prefixes(start_year: int, end_year: int) -> set[str]:
    return {f"{year % 100:02d}{(year + 1) % 100:02d}" for year in range(start_year, end_year + 1)}


def load_rows(source: Path, start_year: int, end_year: int) -> list[dict[str, Any]]:
    """Load rows with both half-time outcomes and closing/pre-match 1X2 odds."""
    rows = []
    prefixes = _season_prefixes(start_year, end_year)
    for directory in LEAGUES:
        for path in sorted((source / directory).glob("*.csv")):
            if path.name[:4] not in prefixes:
                continue
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    try:
                        ft_home, ft_away = int(float(row["FTHG"])), int(float(row["FTAG"]))
                        ht_home, ht_away = int(float(row["HTHG"])), int(float(row["HTAG"]))
                        day = datetime.strptime(str(row["Date"]), "%d/%m/%Y").date().isoformat()
                    except (KeyError, TypeError, ValueError):
                        continue
                    odds = [_number(row, "PSCH", "AvgCH", "B365CH"),
                            _number(row, "PSCD", "AvgCD", "B365CD"),
                            _number(row, "PSCA", "AvgCA", "B365CA")]
                    if any(value is None for value in odds):
                        continue
                    label = hafu_label(ht_home, ht_away, ft_home, ft_away)
                    rows.append({"day": day, "league": directory, "odds": odds,
                                 "actual_idx": STATES.index(label)})
    return sorted(rows, key=lambda row: (row["day"], row["league"]))


def _solve_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Worker-safe reconstruction of production's market-derived HAFU baseline."""
    core = str(CORE)
    if core not in sys.path:
        sys.path.insert(0, core)
    import market_fit  # type: ignore[import-not-found]
    import predict  # type: ignore[import-not-found]

    try:
        probs, _ = predict.devig([float(value) for value in row["odds"]], "power")
        lambdas = predict.solve_lam_from_probs(probs)
        if lambdas is None:
            return None
        raw_probs = market_fit.hafu_probs(float(lambdas[0]), float(lambdas[1]),
                                          predict.matrix, predict.RHO_DEFAULT)
        if len(raw_probs) != len(STATES) or not math.isclose(sum(raw_probs), 1.0, abs_tol=1e-6):
            return None
        return {"day": row["day"], "league": row["league"], "actual_idx": row["actual_idx"],
                "raw_probs": raw_probs}
    except (ArithmeticError, TypeError, ValueError):
        return None


def build_predictions(rows: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    if workers <= 1:
        return [output for output in (_solve_row(row) for row in rows) if output is not None]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return [output for output in pool.map(_solve_row, rows, chunksize=32) if output is not None]


def fit_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 2:
        return {"status": "insufficient_rows", "n": len(rows)}
    split = int(len(rows) * 0.70)
    train, test = rows[:split], rows[split:]
    options = [{"temperature": temperature, "train": metrics(train, temperature)}
               for temperature in TEMPERATURE_GRID]
    best = min(options, key=lambda item: item["train"]["log_loss"])
    default_test = metrics(test, 1.0)
    candidate_test = metrics(test, best["temperature"])
    gain = default_test["log_loss"] - candidate_test["log_loss"]
    adopt = len(test) >= MIN_TEST_N and gain >= MIN_LOGLOSS_GAIN
    return {
        "status": "ok", "n": len(rows), "train_n": len(train), "test_n": len(test),
        "train_end": train[-1]["day"], "test_start": test[0]["day"], "test_end": test[-1]["day"],
        "production_default": {"temperature": 1.0, "test": default_test},
        "train_best": {**best, "test": candidate_test},
        "test_log_loss_improvement": round(gain, 6),
        "adopt_for_research": adopt,
        "adopt_reason": ("time_split_logloss_gain" if adopt else "keep_unfitted_pending_evidence"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="半全场九态温度校准研究；不改生产参数")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, default=OUT / "hafu_temperature_time_split.json")
    args = parser.parse_args()
    raw = load_rows(args.source, args.start_year, args.end_year)
    predicted = build_predictions(raw, max(1, args.workers))
    report = {
        "schema": "hafu-temperature-calibration-1.0", "research_only": True,
        "production_unchanged": True,
        "source": "Football-Data.co.uk Big5 historical closing 1X2 + HT/FT results",
        "market_isolation": "International closing odds are research calibration only; Sporttery remains production input.",
        "period": {"start_year": args.start_year, "end_year": args.end_year},
        "raw_rows": len(raw), "solver_rows": len(predicted),
        "result": fit_report(predicted),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(args.output), "raw_rows": len(raw),
                      "solver_rows": len(predicted), "result": report["result"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
