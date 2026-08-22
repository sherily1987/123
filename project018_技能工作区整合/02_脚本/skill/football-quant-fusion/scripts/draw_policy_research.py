#!/usr/bin/env python3
"""Evaluate a draw-watch policy without changing production probabilities.

The policy is deliberately a label-only research overlay.  It uses the
already-calibrated 1X2 probabilities and may mark a close match as ``draw``;
it never changes ``final_1x2_pct`` or recommends a wager.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Iterable

from runtime_paths import backtest_store, core_scripts_dir


DEFAULT_MARGINS = tuple(round(index * 0.0025, 4) for index in range(61))


def choose_label(probabilities: Iterable[float], draw_margin: float = 0.0) -> int:
    """Return H/D/A index, allowing D only when it is close to the leader."""
    values = tuple(float(value) for value in probabilities)
    if len(values) != 3:
        raise ValueError("probabilities must contain exactly H/D/A")
    if draw_margin < 0:
        raise ValueError("draw_margin must be non-negative")
    leader = max(values[0], values[2])
    return 1 if values[1] >= leader - draw_margin else max(range(3), key=values.__getitem__)


def policy_metrics(rows: list[dict], draw_margin: float) -> dict:
    """Score a label-only policy; no probability is modified."""
    if not rows:
        return {"n": 0, "draw_precision": None, "draw_recall": None, "draw_f1": None}
    predicted = [choose_label(row["probabilities"], draw_margin) for row in rows]
    actual = [int(row["actual"]) for row in rows]
    true_positive = sum(pred == 1 and outcome == 1 for pred, outcome in zip(predicted, actual))
    false_positive = sum(pred == 1 and outcome != 1 for pred, outcome in zip(predicted, actual))
    false_negative = sum(pred != 1 and outcome == 1 for pred, outcome in zip(predicted, actual))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": len(rows),
        "overall_accuracy": sum(pred == outcome for pred, outcome in zip(predicted, actual)) / len(rows),
        "draw_predictions": sum(pred == 1 for pred in predicted),
        "actual_draws": sum(outcome == 1 for outcome in actual),
        "draw_precision": precision,
        "draw_recall": recall,
        "draw_f1": f1,
    }


def select_margin(
    train_rows: list[dict], *, margins: Iterable[float] = DEFAULT_MARGINS,
    max_overall_accuracy_loss: float = 0.005, min_draw_precision: float = 0.30,
) -> dict:
    """Select a draw-watch threshold only from pre-holdout rows.

    Maximising draw F1 alone would turn most close fixtures into draws.  A
    candidate is eligible only if it preserves train 1X2 accuracy within the
    stated tolerance and its draw precision clears the declared floor.
    """
    baseline = policy_metrics(train_rows, 0.0)
    candidates = []
    for margin in sorted({float(value) for value in margins}):
        metrics = policy_metrics(train_rows, margin)
        if (
            metrics["draw_predictions"]
            and metrics["overall_accuracy"] >= baseline["overall_accuracy"] - max_overall_accuracy_loss
            and metrics["draw_precision"] >= min_draw_precision
        ):
            candidates.append((metrics["draw_f1"], metrics["draw_precision"], metrics["overall_accuracy"], -margin, margin, metrics))
    if not candidates:
        return {
            "decision": "hold",
            "reason_code": "NO_TRAIN_MARGIN_PASSES_GUARDS",
            "baseline_metrics": baseline,
            "research_only": True,
            "production_probabilities_changed": False,
        }
    _, _, _, _, margin, metrics = max(candidates)
    return {
        "decision": "selected_for_out_of_time_evaluation",
        "margin": margin,
        "metrics": metrics,
        "baseline_metrics": baseline,
        "guards": {
            "max_overall_accuracy_loss": max_overall_accuracy_loss,
            "min_draw_precision": min_draw_precision,
        },
        "research_only": True,
        "production_probabilities_changed": False,
    }


def _core_predict():
    core_dir = str(core_scripts_dir())
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)
    return importlib.import_module("predict")


def extract_snapshot_rows(snapshot_path: Path) -> list[dict]:
    """Build calibrated probability rows from official pre-kickoff HAD quotes."""
    predict = _core_predict()
    rows = []
    labels = {"H": 0, "D": 1, "A": 2}
    for line in snapshot_path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        outcome = labels.get(raw.get("result_1x2"))
        closing = ((raw.get("snapshots") or {}).get("closing") or {}).get("odds")
        if outcome is None or not raw.get("kickoff") or not closing:
            continue
        try:
            market_probabilities, _ = predict.devig([float(value) for value in closing], "power")
            calibration = predict.league_calibration({"competition": raw.get("competition", "")})
            probabilities = predict.calibrate_1x2(
                market_probabilities, calibration["draw_k"], calibration["temperature"],
            )
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        rows.append({
            "match_id": raw.get("match_id"), "day": str(raw["kickoff"])[:10],
            "probabilities": tuple(float(value) for value in probabilities), "actual": outcome,
        })
    return sorted(rows, key=lambda row: (row["day"], str(row.get("match_id") or "")))


def chronological_evaluation(
    rows: list[dict], *, test_fraction: float = 0.30, margins: Iterable[float] = DEFAULT_MARGINS,
    max_overall_accuracy_loss: float = 0.005, min_draw_precision: float = 0.30,
) -> dict:
    """Select on earlier days and evaluate the frozen label policy on later days."""
    if not 0.05 <= test_fraction < 0.50:
        raise ValueError("test_fraction must be in [0.05, 0.50)")
    days = sorted({row["day"] for row in rows})
    if len(days) < 2:
        raise ValueError("need at least two match days")
    split_index = max(1, min(len(days) - 1, int(len(days) * (1.0 - test_fraction))))
    test_from = days[split_index]
    train_rows = [row for row in rows if row["day"] < test_from]
    test_rows = [row for row in rows if row["day"] >= test_from]
    selected = select_margin(
        train_rows, margins=margins, max_overall_accuracy_loss=max_overall_accuracy_loss,
        min_draw_precision=min_draw_precision,
    )
    report = {
        "schema_version": "sporttery-draw-watch-research-1.0",
        "research_only": True,
        "production_probabilities_changed": False,
        "source_policy": "official Sporttery closing HAD -> existing power devig + existing league calibration",
        "split": {"method": "chronological_by_match_day", "train_n": len(train_rows), "test_n": len(test_rows),
                  "train_through": train_rows[-1]["day"], "test_from": test_from},
        "train_selection": selected,
        "test_baseline_argmax": policy_metrics(test_rows, 0.0),
    }
    if selected["decision"] == "selected_for_out_of_time_evaluation":
        report["test_draw_watch"] = policy_metrics(test_rows, selected["margin"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=backtest_store() / "snapshots" / "sporttery_all_leagues_2026.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    parser.add_argument("--max-overall-accuracy-loss", type=float, default=0.005)
    parser.add_argument("--min-draw-precision", type=float, default=0.30)
    args = parser.parse_args()
    rows = extract_snapshot_rows(args.input)
    report = chronological_evaluation(
        rows, test_fraction=args.test_fraction, max_overall_accuracy_loss=args.max_overall_accuracy_loss,
        min_draw_precision=args.min_draw_precision,
    )
    report["source_file"] = str(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
