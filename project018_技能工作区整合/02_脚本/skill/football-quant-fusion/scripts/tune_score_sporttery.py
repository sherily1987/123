#!/usr/bin/env python3
"""Time-split exact-score tuning on the same Sporttery HAD source as production.

This is deliberately a research-only tuner.  It reconstructs the production
market-only lambdas from a pre-kickoff Sporttery HAD snapshot, then tests only
the BP shared-goal coefficient (``lambda3``) against 90-minute score results.
It never uses post-kickoff data as an input and never writes core parameters.

Important semantics: the production ``score_matrix`` is the *raw* BP matrix.
Temperature is used only to display/rank ``top_scores`` and, being monotonic,
cannot improve the Top-N hit rate.  Thus matrix likelihood and score ranking
are reported separately here.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]
CORE = PROJECT / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
DEFAULT_LAMBDA3 = 0.05
# Keep search values above the currently released 0.20.  A grid that ends at
# the incumbent cannot distinguish a genuine optimum from a boundary artifact.
LAMBDA3_GRID = (0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
MIN_TEST_N = 120
MIN_LOGLOSS_GAIN = 0.005


def _predict_module():
    core = str(CORE)
    if core not in sys.path:
        sys.path.insert(0, core)
    import predict  # type: ignore[import-not-found]
    return predict


def _score_text(score: Any) -> str | None:
    if not isinstance(score, (list, tuple)) or len(score) < 2:
        return None
    try:
        home, away = int(score[0]), int(score[1])
    except (TypeError, ValueError):
        return None
    if home < 0 or away < 0:
        return None
    return f"{home}-{away}"


def _solve_snapshot(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Worker-safe HAD-to-lambda reconstruction; contains no future result input."""
    predict = _predict_module()
    try:
        odds = record["odds"]
        probs, _ = predict.devig([float(value) for value in odds], "power")
        lambdas = predict.solve_lam_from_probs(probs)
        if lambdas is None:
            return None
        home_lambda, away_lambda = float(lambdas[0]), float(lambdas[1])
        if min(home_lambda, away_lambda) < 0:
            return None
        return {**record, "lambdas": (home_lambda, away_lambda)}
    except (AttributeError, TypeError, ValueError):
        return None


def load_rows(path: Path, workers: int = 1) -> list[dict[str, Any]]:
    """Read only closing/pre-kickoff HAD and verified 90-minute scores."""
    raw_rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            closing = (record.get("snapshots") or {}).get("closing") or {}
            odds = closing.get("odds")
            actual_score = _score_text(record.get("score_90"))
            day = str(record.get("kickoff") or "")
            if not actual_score or len(day) < 10:
                continue
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        raw_rows.append({"day": day[:10], "match_id": str(record.get("match_id") or ""),
                         "league": str(record.get("competition") or ""), "odds": odds,
                         "actual_score": actual_score})
    if workers <= 1:
        rows = [row for row in (_solve_snapshot(row) for row in raw_rows) if row is not None]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = [row for row in pool.map(_solve_snapshot, raw_rows, chunksize=16) if row is not None]
    return sorted(rows, key=lambda row: (row["day"], row["match_id"]))


def _binary_metrics(values: Iterable[tuple[float, int]]) -> dict[str, float | int | None]:
    briers: list[float] = []
    losses: list[float] = []
    hits: list[bool] = []
    for probability, actual in values:
        if not 0.0 <= probability <= 1.0 or actual not in (0, 1):
            continue
        briers.append((probability - actual) ** 2)
        losses.append(-(actual * math.log(max(probability, 1e-15))
                        + (1 - actual) * math.log(max(1.0 - probability, 1e-15))))
        hits.append((probability >= 0.5) == bool(actual))
    n = len(briers)
    return {"n": n, "brier": round(sum(briers) / n, 6) if n else None,
            "log_loss": round(sum(losses) / n, 6) if n else None,
            "accuracy_pct": round(100.0 * sum(hits) / n, 2) if n else None}


def matrix_metrics(rows: Iterable[Mapping[str, Any]], lambda3: float) -> dict[str, Any]:
    """Score raw production-matrix likelihood plus unchanged rank accuracy."""
    predict = _predict_module()
    losses: list[float] = []
    top1 = top3 = 0
    ou_values: dict[float, list[tuple[float, int]]] = {2.5: [], 3.5: []}
    for row in rows:
        try:
            home_lambda, away_lambda = row["lambdas"]
            matrix = predict.bp_matrix(float(home_lambda), float(away_lambda), float(lambda3))
            home_text, away_text = str(row["actual_score"]).split("-", 1)
            actual = (int(home_text), int(away_text))
            probability = float(matrix[actual])
        except (KeyError, TypeError, ValueError):
            continue
        losses.append(-math.log(max(probability, 1e-15)))
        ranked = sorted(matrix, key=matrix.__getitem__, reverse=True)
        top1 += int(actual == ranked[0])
        top3 += int(actual in ranked[:3])
        total_goals = actual[0] + actual[1]
        for line in ou_values:
            # Use the existing production Platt layer on both branches.  This
            # tests the full downstream consequence of changing lambda3, not
            # a more flattering uncalibrated proxy.
            over = float(predict.ou(matrix, line)["over_pct"]) / 100.0
            ou_values[line].append((over, int(total_goals > line)))
    n = len(losses)
    return {
        "n": n,
        "score_log_loss": round(sum(losses) / n, 6) if n else None,
        "top1_accuracy_pct": round(100.0 * top1 / n, 2) if n else None,
        "top3_accuracy_pct": round(100.0 * top3 / n, 2) if n else None,
        "ou_2_5": _binary_metrics(ou_values[2.5]),
        "ou_3_5": _binary_metrics(ou_values[3.5]),
    }


def fit_report(rows: list[dict[str, Any]], *, lambda_grid: Iterable[float] = LAMBDA3_GRID,
               min_test_n: int = MIN_TEST_N) -> dict[str, Any]:
    """Choose by train raw-matrix log loss, then disclose an untouched test."""
    if len(rows) < 2:
        return {"schema": "sporttery-score-lambda3-1.0", "research_only": True,
                "production_unchanged": True, "status": "insufficient_rows", "n": len(rows)}
    # A calendar day is the smallest reliable timing unit in this historical
    # file.  Never put matches from one day on both sides: doing so lets a
    # parameter fit see some same-day outcomes before evaluating other games
    # whose precise kickoff ordering is unavailable/ambiguous in the export.
    target = max(1, int(len(rows) * 0.70))
    split = next((index for index in range(target, len(rows))
                  if rows[index - 1]["day"] < rows[index]["day"]), None)
    if split is None:
        return {"schema": "sporttery-score-lambda3-1.0", "research_only": True,
                "production_unchanged": True, "status": "insufficient_distinct_days", "n": len(rows)}
    train, test = rows[:split], rows[split:]
    baseline_train = matrix_metrics(train, DEFAULT_LAMBDA3)
    baseline_test = matrix_metrics(test, DEFAULT_LAMBDA3)
    options = []
    for lambda3 in lambda_grid:
        candidate = matrix_metrics(train, float(lambda3))
        if candidate["score_log_loss"] is not None:
            options.append({"lambda3": float(lambda3), "train": candidate})
    if not options:
        return {"schema": "sporttery-score-lambda3-1.0", "research_only": True,
                "production_unchanged": True, "status": "no_valid_matrices", "n": len(rows)}
    chosen = min(options, key=lambda option: float(option["train"]["score_log_loss"]))
    candidate_lambda3 = float(chosen["lambda3"])
    candidate_test = matrix_metrics(test, candidate_lambda3)
    baseline_loss = baseline_test["score_log_loss"]
    candidate_loss = candidate_test["score_log_loss"]
    delta = (round(float(candidate_loss) - float(baseline_loss), 6)
             if baseline_loss is not None and candidate_loss is not None else None)
    ou_deltas: dict[str, float | None] = {}
    ou_not_worse = True
    for key in ("ou_2_5", "ou_3_5"):
        base_brier = baseline_test[key]["brier"]
        candidate_brier = candidate_test[key]["brier"]
        brier_delta = (round(float(candidate_brier) - float(base_brier), 6)
                       if base_brier is not None and candidate_brier is not None else None)
        ou_deltas[key] = brier_delta
        ou_not_worse = ou_not_worse and brier_delta is not None and brier_delta <= 0.0
    score_wins = (candidate_lambda3 != DEFAULT_LAMBDA3 and len(test) >= min_test_n
                  and delta is not None and delta <= -MIN_LOGLOSS_GAIN)
    adopt = score_wins and ou_not_worse
    if adopt:
        reason = "same_source_time_split_score_gain_without_ou_brier_regression"
    elif score_wins:
        reason = "score_gain_but_ou_brier_regressed"
    else:
        reason = "keep_current_pending_same_source_gain"
    def score_part(metrics: Mapping[str, Any]) -> dict[str, Any]:
        return {key: metrics.get(key) for key in ("n", "score_log_loss", "top1_accuracy_pct", "top3_accuracy_pct")}

    return {
        "schema": "sporttery-score-lambda3-1.0",
        "research_only": True,
        "production_unchanged": True,
        "status": "ok",
        "n": len(rows),
        "train_n": len(train),
        "test_n": len(test),
        "train_end": train[-1]["day"],
        "test_start": test[0]["day"],
        "test_end": test[-1]["day"],
        "selection_metric": "train_raw_score_matrix_log_loss",
        "baseline": {"lambda3": DEFAULT_LAMBDA3, "score_matrix_temperature": 1.0},
        "candidate": {"lambda3": candidate_lambda3, "score_matrix_temperature": 1.0,
                      "top_scores_temperature": None},
        "train": {"baseline": baseline_train, "candidate": chosen["train"]},
        "test": {"baseline": {"score_matrix": score_part(baseline_test),
                                 "ou_2_5": baseline_test["ou_2_5"],
                                 "ou_3_5": baseline_test["ou_3_5"]},
                 "candidate": {"score_matrix": score_part(candidate_test),
                               "ou_2_5": candidate_test["ou_2_5"],
                               "ou_3_5": candidate_test["ou_3_5"]},
                 "delta_log_loss_candidate_minus_baseline": delta,
                 "delta_ou_brier_candidate_minus_baseline": ou_deltas,
                 "ou_non_regression_required": True,
                 "ou_non_regression_passed": ou_not_worse},
        "adopt_for_research": adopt,
        "adopt_reason": reason,
        "note": ("Temperature is excluded from the score-matrix comparison because the current "
                 "production score_matrix is raw; temperature cannot change Top-N ranking."),
    }


def main() -> None:
    from runtime_paths import backtest_store  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser(description="体彩同源比分λ3时间切分研究；不修改生产参数")
    parser.add_argument("--input", type=Path,
                        default=backtest_store() / "snapshots" / "sporttery_all_leagues_2026.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-test-n", type=int, default=MIN_TEST_N)
    parser.add_argument("--workers", type=int, default=4,
                        help="并行重建盘口lambda的进程数；默认4")
    args = parser.parse_args()
    if args.min_test_n < 1:
        parser.error("--min-test-n must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")
    rows = load_rows(args.input, workers=args.workers)
    report = fit_report(rows, min_test_n=args.min_test_n)
    report["input"] = str(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report.get("status"), "output": str(args.output),
                      "n": report.get("n"), "test": report.get("test"),
                      "adopt_for_research": report.get("adopt_for_research")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
