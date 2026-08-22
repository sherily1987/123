#!/usr/bin/env python3
"""Chronologically test a TTG-conditioned draw-probability shadow candidate."""
from __future__ import annotations

import argparse
import importlib
import json
import math
import random
import sys
from pathlib import Path

from draw_watch_signal import ttg_under2_probability
from runtime_paths import core_scripts_dir


THRESHOLD_GRID = (0.35, 0.40, 0.45, 0.50, 0.55)
FOCUS_K_GRID = tuple(round(0.80 + step * 0.05, 2) for step in range(13))
OTHER_K_GRID = tuple(round(0.80 + step * 0.05, 2) for step in range(9))


def reweight_draw(probabilities: list[float], draw_weight: float) -> list[float]:
    """Renormalize after changing only the draw component's relative weight."""
    if len(probabilities) != 3 or draw_weight <= 0:
        raise ValueError("need H/D/A probabilities and a positive draw weight")
    weighted = [float(probabilities[0]), float(probabilities[1]) * float(draw_weight), float(probabilities[2])]
    total = sum(weighted)
    if total <= 0 or any(not math.isfinite(value) or value < 0 for value in weighted):
        raise ValueError("invalid probability vector")
    return [value / total for value in weighted]


def _core_predict():
    source = str(core_scripts_dir())
    if source not in sys.path:
        sys.path.insert(0, source)
    return importlib.import_module("predict")


def _had_outcome(match: dict) -> int | None:
    for item in match.get("match_result_list") or []:
        if str(item.get("code") or "").upper() == "HAD":
            return {"H": 0, "D": 1, "A": 2}.get(str(item.get("combination") or "").upper())
    return None


def extract_rows(source: Path) -> list[dict]:
    """Use only official closing pre-kickoff market rows and HAD settlement."""
    predict = _core_predict()
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    rows = []
    for match in payload.get("matches") or []:
        outcome = _had_outcome(match)
        closing = match.get("closing_pre_match") or {}
        had = closing.get("had") or {}
        try:
            odds = [float(had[key]) for key in ("h", "d", "a")]
        except (KeyError, TypeError, ValueError):
            continue
        under2 = ttg_under2_probability(closing.get("ttg"))
        if outcome is None or under2 is None or not match.get("kickoff_iso"):
            continue
        try:
            market, _ = predict.devig(odds, "power")
            calibration = predict.league_calibration({"competition": match.get("leagueAbbName", "")})
            probabilities = predict.calibrate_1x2(market, calibration["draw_k"], calibration["temperature"])
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        rows.append({
            "day": str(match["kickoff_iso"])[:10], "match_id": match.get("matchId"),
            "probabilities": [float(value) for value in probabilities], "actual": outcome, "ttg_under2": under2,
        })
    return sorted(rows, key=lambda row: (row["day"], str(row["match_id"])))


def candidate_probabilities(row: dict, threshold: float, focus_draw_k: float, other_draw_k: float) -> list[float]:
    weight = focus_draw_k if float(row["ttg_under2"]) >= threshold else other_draw_k
    return reweight_draw(row["probabilities"], weight)


def metrics(rows: list[dict], threshold: float, focus_draw_k: float, other_draw_k: float) -> dict:
    if not rows:
        return {"n": 0}
    brier = logloss = draw_brier = correct = 0.0
    draw_sum = actual_draws = 0
    for row in rows:
        probability = candidate_probabilities(row, threshold, focus_draw_k, other_draw_k)
        actual = int(row["actual"])
        brier += sum((value - float(index == actual)) ** 2 for index, value in enumerate(probability))
        logloss -= math.log(max(probability[actual], 1e-12))
        draw_brier += (probability[1] - float(actual == 1)) ** 2
        correct += int(max(range(3), key=probability.__getitem__) == actual)
        draw_sum += probability[1]
        actual_draws += int(actual == 1)
    n = len(rows)
    return {
        "n": n, "one_x2_brier": brier / n, "one_x2_logloss": logloss / n,
        "draw_brier": draw_brier / n, "top1_accuracy": correct / n,
        "mean_draw_probability": draw_sum / n, "actual_draw_rate": actual_draws / n,
    }


def fit_candidate(train_rows: list[dict]) -> dict:
    """Choose the compact candidate using only earlier match days and log loss."""
    choices = []
    for threshold in THRESHOLD_GRID:
        for focus_k in FOCUS_K_GRID:
            for other_k in OTHER_K_GRID:
                result = metrics(train_rows, threshold, focus_k, other_k)
                choices.append((result["one_x2_logloss"], result["one_x2_brier"], result["draw_brier"],
                                threshold, focus_k, other_k, result))
    _, _, _, threshold, focus_k, other_k, selected_metrics = min(choices)
    return {"ttg_under2_threshold": threshold, "focus_draw_k": focus_k, "other_draw_k": other_k,
            "train_metrics": selected_metrics, "selection_metric": "one_x2_logloss"}


def _quantile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lo, hi = int(position), math.ceil(position)
    return values[lo] if lo == hi else values[lo] + (values[hi] - values[lo]) * (position - lo)


def paired_bootstrap(rows: list[dict], candidate: dict, draws: int = 2000, seed: int = 20260822) -> dict:
    deltas = {"one_x2_brier": [], "one_x2_logloss": [], "draw_brier": []}
    for row in rows:
        base = row["probabilities"]
        shadow = candidate_probabilities(row, candidate["ttg_under2_threshold"],
                                         candidate["focus_draw_k"], candidate["other_draw_k"])
        actual = int(row["actual"])
        deltas["one_x2_brier"].append(
            sum((shadow[index] - float(index == actual)) ** 2 - (base[index] - float(index == actual)) ** 2
                for index in range(3)))
        deltas["one_x2_logloss"].append(-math.log(max(shadow[actual], 1e-12)) + math.log(max(base[actual], 1e-12)))
        deltas["draw_brier"].append((shadow[1] - float(actual == 1)) ** 2 - (base[1] - float(actual == 1)) ** 2)
    rng = random.Random(seed)

    def summarize(values: list[float]) -> dict:
        samples = [sum(values[rng.randrange(len(values))] for _ in range(len(values))) / len(values)
                   for _ in range(draws)]
        return {"delta_shadow_minus_base": sum(values) / len(values),
                "ci95_low": _quantile(samples, 0.025), "ci95_high": _quantile(samples, 0.975)}

    return {"n": len(rows), "draws": draws, "seed": seed,
            **{name: summarize(values) for name, values in deltas.items()}}


def admission_decision(paired: dict, test_n: int, minimum_test_n: int = 200) -> dict:
    if test_n < minimum_test_n:
        return {"decision": "hold", "reason_code": "TEST_SAMPLE_BELOW_MINIMUM", "minimum_test_n": minimum_test_n}
    needed = ("one_x2_brier", "one_x2_logloss", "draw_brier")
    if not all(isinstance(paired.get(name), dict) and paired[name].get("ci95_high", 0) < 0 for name in needed):
        return {"decision": "hold", "reason_code": "PAIRED_INTERVAL_NOT_DECISIVE", "minimum_test_n": minimum_test_n}
    return {"decision": "eligible_for_review", "reason_code": "ALL_PAIRED_INTERVALS_IMPROVE",
            "minimum_test_n": minimum_test_n}


def evaluate(rows: list[dict], test_fraction: float = 0.30, bootstrap_draws: int = 2000) -> dict:
    days = sorted({row["day"] for row in rows})
    if len(days) < 2:
        raise ValueError("need at least two match days")
    split = max(1, min(len(days) - 1, int(len(days) * (1.0 - test_fraction))))
    test_from = days[split]
    train, test = [row for row in rows if row["day"] < test_from], [row for row in rows if row["day"] >= test_from]
    candidate = fit_candidate(train)
    baseline = metrics(test, 0.45, 1.0, 1.0)
    candidate_test = metrics(test, candidate["ttg_under2_threshold"], candidate["focus_draw_k"], candidate["other_draw_k"])
    paired = paired_bootstrap(test, candidate, draws=bootstrap_draws)
    return {
        "schema_version": "sporttery-ttg-draw-shadow-research-1.0", "research_only": True,
        "production_probability_adjustment_applied": False,
        "source_policy": "official Sporttery closing HAD + TTG only; same-book derivative, not independent evidence",
        "split": {"method": "chronological_by_match_day", "train_n": len(train), "test_n": len(test),
                  "train_through": train[-1]["day"], "test_from": test_from},
        "candidate": candidate, "test_baseline": baseline, "test_shadow": candidate_test,
        "test_paired_bootstrap": paired, "admission": admission_decision(paired, len(test)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    args = parser.parse_args()
    if not 0.05 <= args.test_fraction < 0.50 or args.bootstrap_draws < 100:
        parser.error("test fraction must be [0.05, 0.50) and bootstrap draws must be >= 100")
    report = evaluate(extract_rows(args.input), args.test_fraction, args.bootstrap_draws)
    report["source_file"] = str(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
