#!/usr/bin/env python3
"""Three-way time backtest for historical calibration of each Sporttery odds pool."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import market_specific_odds_evaluation as mse
from independent_lambda_market_shadow import bet_policy_metrics


def fit_class_bias(rows: list[dict[str, Any]], *, prior_matches: float = 50.0) -> list[float]:
    if not rows:
        return []
    classes = len(rows[0]["direct"])
    predicted = [sum(float(row["direct"][i]) for row in rows) for i in range(classes)]
    actual = [sum(int(row["actual"]) == i for row in rows) for i in range(classes)]
    average = [value / len(rows) for value in predicted]
    return [
        (actual[i] + prior_matches * average[i])
        / (predicted[i] + prior_matches * average[i])
        if predicted[i] + prior_matches * average[i] > 0 else 1.0
        for i in range(classes)
    ]


def _apply_bias(probabilities: list[float], factors: list[float]) -> list[float]:
    adjusted = [max(1e-12, float(probability) * float(factor)) for probability, factor in zip(probabilities, factors)]
    total = sum(adjusted)
    return [value / total for value in adjusted]


def _probability_metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    brier = []
    logloss = []
    correct = 0
    for row in rows:
        probability = row[key]
        actual = int(row["actual"])
        brier.append(sum((value - float(i == actual)) ** 2 for i, value in enumerate(probability)))
        logloss.append(-math.log(max(float(probability[actual]), 1e-12)))
        correct += max(range(len(probability)), key=probability.__getitem__) == actual
    return {
        "n": len(rows),
        "multiclass_brier": round(sum(brier) / len(rows), 8),
        "log_loss": round(sum(logloss) / len(rows), 8),
        "top1_accuracy_pct": round(correct * 100.0 / len(rows), 2),
    }


def _bootstrap_delta(rows: list[dict[str, Any]], *, draws: int = 3000, seed: int = 20260823) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "brier_ci95": None, "logloss_ci95": None}
    deltas = []
    for row in rows:
        actual = int(row["actual"])
        direct = row["direct"]
        calibrated = row["calibrated"]
        deltas.append((
            sum((calibrated[i] - float(i == actual)) ** 2 - (direct[i] - float(i == actual)) ** 2 for i in range(len(direct))),
            -math.log(max(calibrated[actual], 1e-12)) + math.log(max(direct[actual], 1e-12)),
        ))
    rng = random.Random(seed)

    def ci(index: int) -> list[float]:
        sampled = sorted(
            sum(deltas[rng.randrange(len(deltas))][index] for _ in deltas) / len(deltas)
            for _ in range(draws)
        )
        lo = sampled[int(0.025 * (draws - 1))]
        hi = sampled[int(0.975 * (draws - 1))]
        return [round(lo, 8), round(hi, 8)]

    return {"n": len(rows), "brier_ci95": ci(0), "logloss_ci95": ci(1)}


def _candidate_bets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        choices = [
            (i, probability, float(row["odds"][i]), probability * float(row["odds"][i]) - 1.0)
            for i, probability in enumerate(row["calibrated"])
            if float(row["odds"][i]) > 1.0
        ]
        if not choices:
            continue
        index, probability, odds, raw_ev = max(choices, key=lambda value: value[3])
        if raw_ev <= 0:
            continue
        won = index == int(row["actual"])
        output.append({
            "match_id": row.get("match_id"),
            "kickoff": row.get("day"),
            "selection": row["labels"][index],
            "odds": odds,
            "raw_ev": raw_ev,
            "won": won,
            "profit_units": odds - 1.0 if won else -1.0,
        })
    return output


def _select_policy(
    validation_rows: list[dict[str, Any]],
    *,
    minimum_bets: int,
) -> tuple[dict[str, float] | None, dict[str, Any]]:
    bets = _candidate_bets(validation_rows)
    candidates = []
    for threshold in (0.0, 0.02, 0.05, 0.10, 0.20):
        for cap in (3.0, 5.0, 10.0, 20.0, 1000.0):
            selected = [row for row in bets if row["raw_ev"] >= threshold and row["odds"] <= cap]
            metrics = bet_policy_metrics(selected)
            if metrics["n"] >= minimum_bets:
                candidates.append((threshold, cap, metrics))
    if not candidates:
        return None, bet_policy_metrics([])
    threshold, cap, metrics = max(
        candidates,
        key=lambda value: (float(value[2]["roi"]), value[2]["n"], -value[1], -value[0]),
    )
    return {"minimum_raw_ev": threshold, "maximum_odds": cap}, metrics


def _apply_policy(rows: list[dict[str, Any]], policy: dict[str, float] | None) -> list[dict[str, Any]]:
    if not policy:
        return []
    return [
        row for row in _candidate_bets(rows)
        if row["raw_ev"] >= policy["minimum_raw_ev"] and row["odds"] <= policy["maximum_odds"]
    ]


def three_way_market_backtest(
    rows: list[dict[str, Any]],
    *,
    fit_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    prior_matches: float = 50.0,
    minimum_validation_bets: int = 20,
    minimum_test_bets: int = 20,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("day") or ""), str(row.get("match_id") or "")))
    days = sorted({str(row.get("day") or "") for row in ordered})
    fit_end = max(1, min(len(days) - 2, int(len(days) * fit_fraction)))
    validation_end = max(fit_end + 1, min(len(days) - 1, int(len(days) * (fit_fraction + validation_fraction))))
    fit_until, test_from = days[fit_end], days[validation_end]
    fit = [row for row in ordered if row["day"] < fit_until]
    validation = [row for row in ordered if fit_until <= row["day"] < test_from]
    test = [row for row in ordered if row["day"] >= test_from]
    factors = fit_class_bias(fit, prior_matches=prior_matches)

    def calibrated(segment: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**row, "calibrated": _apply_bias(row["direct"], factors)} for row in segment]

    validation_calibrated = calibrated(validation)
    test_calibrated = calibrated(test)
    policy, validation_bets = _select_policy(validation_calibrated, minimum_bets=minimum_validation_bets)
    test_bets = bet_policy_metrics(_apply_policy(test_calibrated, policy))
    paired = _bootstrap_delta(test_calibrated)
    calibrated_metrics = _probability_metrics(test_calibrated, "calibrated")
    direct_metrics = _probability_metrics(test_calibrated, "direct")
    probability_better = bool(
        paired["brier_ci95"] and paired["logloss_ci95"]
        and paired["brier_ci95"][1] < 0 and paired["logloss_ci95"][1] < 0
    )
    if validation_bets["n"] < minimum_validation_bets:
        decision, reason = "hold", "insufficient_validation_bets"
    elif test_bets["n"] < minimum_test_bets:
        decision, reason = "hold", "insufficient_final_test_bets"
    elif not probability_better:
        decision, reason = "hold", "calibrated_probability_not_significantly_better_than_market"
    elif (validation_bets["roi"] or 0.0) <= 0 or (test_bets["roi"] or 0.0) <= 0:
        decision, reason = "hold", "roi_not_positive_in_validation_and_final_test"
    elif (test_bets["largest_winner_profit_share"] or 1.0) > 0.5:
        decision, reason = "hold", "final_test_profit_concentrated_in_one_winner"
    else:
        decision, reason = "candidate_review", "probability_and_betting_policy_passed_three_way_test"
    classes = len(rows[0]["labels"]) if rows else 0
    return {
        "schema": "three-way-market-calibration-backtest-1.0",
        "probability_input": "same_market_odds_power_devig_plus_historical_class_bias",
        "class_bias_fit_used_final_period": False,
        "selected_on": "validation_only",
        "fit_until": fit_until,
        "test_from": test_from,
        "fit_n": len(fit),
        "validation_n": len(validation),
        "test_n": len(test),
        "fit_class_counts": [sum(int(row["actual"]) == i for row in fit) for i in range(classes)],
        "test_class_counts": [sum(int(row["actual"]) == i for row in test) for i in range(classes)],
        "class_bias_factors": [round(value, 8) for value in factors],
        "direct_final_test": direct_metrics,
        "calibrated_final_test": calibrated_metrics,
        "paired_calibrated_minus_direct": paired,
        "selected_policy": policy,
        "validation_bets": validation_bets,
        "final_test_bets": test_bets,
        "decision": decision,
        "reason": reason,
    }


def _crs_prices(match: dict[str, Any], labels: list[str]) -> list[float] | None:
    raw = (match.get("closing_pre_match") or {}).get("crs") or {}
    values = {}
    for key, value in raw.items():
        if len(key) == 6 and key[0] == "s" and key[3] == "s" and not key.endswith("f"):
            try:
                values[f"{int(key[1:3])}:{int(key[4:6])}"] = float(value)
            except (TypeError, ValueError):
                pass
    for key, label in mse.CRS_OTHER_KEYS.items():
        try:
            values[label] = float(raw[key])
        except (KeyError, TypeError, ValueError):
            pass
    return [values[label] for label in labels] if all(label in values for label in labels) else None


def build_market_rows(matches: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    families = {market: [] for market in ("HAD", "TTG", "CRS", "HAFU")}
    for match in matches:
        day = str(match.get("kickoff_iso") or "")[:10]
        if not day:
            continue
        matrix = mse.had_matrix(match)
        builders = {
            "HAD": lambda: mse.direct_had(match),
            "TTG": lambda: mse.direct_ttg(match, matrix) if matrix is not None else None,
            "CRS": lambda: mse.direct_crs(match, matrix) if matrix is not None else None,
            "HAFU": lambda: mse.direct_hafu(match, matrix) if matrix is not None else None,
        }
        closing = match.get("closing_pre_match") or {}
        for market, builder in builders.items():
            row = builder()
            if row is None:
                continue
            if market == "HAD":
                raw = closing.get("had") or {}; odds = [raw.get(key) for key in ("h", "d", "a")]
            elif market == "TTG":
                raw = closing.get("ttg") or {}; odds = [raw.get(f"s{i}") for i in range(8)]
            elif market == "HAFU":
                raw = closing.get("hafu") or {}; odds = [raw.get(label.replace(":", "").lower()) for label in mse.HAFU_LABELS]
            else:
                odds = _crs_prices(match, row["labels"])
            try:
                numeric_odds = [float(value) for value in odds]
            except (TypeError, ValueError):
                continue
            if any(value <= 1.0 for value in numeric_odds):
                continue
            families[market].append({
                "day": day,
                "match_id": f'sporttery-{match.get("matchId")}',
                "labels": row["labels"],
                "direct": row["direct"],
                "actual": row["actual"],
                "odds": numeric_odds,
            })
    return families


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prior-matches", type=float, default=50.0)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    families = build_market_rows(source.get("matches") or [])
    report = {
        "schema": "market-pool-calibration-research-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_change_allowed": False,
        "input": str(args.input.resolve()),
        "markets": {
            market: three_way_market_backtest(rows, prior_matches=args.prior_matches)
            for market, rows in families.items()
        },
        "admission": {
            "decision": "hold",
            "reason": "only individual markets with candidate_review may advance to paper staking",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
