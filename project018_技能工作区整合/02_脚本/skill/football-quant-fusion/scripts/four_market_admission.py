#!/usr/bin/env python3
"""Fail-closed admission check for 1X2, score, O/U and HAFU changes.

It is a governance report, not a switch: no output from this script changes
model_version, production coefficients, or betting recommendations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


MIN_WDL_N = 100
MIN_SCORE_N = 120
MIN_OU_N = 200
MIN_HAFU_N = 200
MIN_SCORE_LOGLOSS_GAIN = 0.005


def _hold(reason: str, **extra: Any) -> dict[str, Any]:
    return {"decision": "hold", "reason": reason, **extra}


def _same_source_score_evidence(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate the dedicated Sporttery score/O-U experiment before using it."""
    if not isinstance(report, Mapping) or report.get("schema") != "sporttery-score-lambda3-1.0":
        return None
    if report.get("research_only") is not True:
        return None
    test = report.get("test")
    candidate = report.get("candidate")
    if not isinstance(test, Mapping) or not isinstance(candidate, Mapping):
        return None
    try:
        test_n = int(report.get("test_n") or 0)
        lambda3 = float(candidate["lambda3"])
        delta = float(test["delta_log_loss_candidate_minus_baseline"])
    except (KeyError, TypeError, ValueError):
        return None
    baseline = test.get("baseline")
    proposed = test.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(proposed, Mapping):
        return None
    try:
        ou_n = min(int(baseline["ou_2_5"]["n"]), int(baseline["ou_3_5"]["n"]),
                   int(proposed["ou_2_5"]["n"]), int(proposed["ou_3_5"]["n"]))
    except (KeyError, TypeError, ValueError):
        return None
    return {"test_n": test_n, "lambda3": lambda3, "score_delta_log_loss": delta,
            "ou_n": ou_n, "ou_non_regression_passed": test.get("ou_non_regression_passed") is True,
            "paired_ci_supports_full_candidate": test.get("paired_ci_supports_full_candidate") is True}


def admission_report(backtest: Mapping[str, Any], derivatives: Mapping[str, Any],
                     score_shadow: Mapping[str, Any],
                     score_time_split: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assess each output family on its own samples; never pool denominators."""
    gate = backtest.get("calibration_gate", {})
    current_n = int(gate.get("current_version_n") or 0)
    wdl = (_hold("current_version_sample_below_minimum", n=current_n, minimum_n=MIN_WDL_N)
           if current_n < MIN_WDL_N else
           {"decision": "review_required", "reason": "sample_threshold_met_but_market_comparison_required",
            "n": current_n, "minimum_n": MIN_WDL_N})

    same_source = _same_source_score_evidence(score_time_split)
    candidate = score_shadow.get("big5_candidate", {})
    score_n = int(candidate.get("n") or 0)
    score_matrix = candidate.get("score_matrix") if isinstance(candidate.get("score_matrix"), Mapping) else {}
    # Pre-2026-08-21 reports used a temperature-scaled matrix as their score
    # likelihood.  It is not a valid production comparator; leave the legacy
    # fallback only so old artifacts fail closed rather than crashing.
    delta = score_matrix.get("delta_log_loss_candidate_minus_baseline")
    if (same_source is not None and same_source["test_n"] >= MIN_SCORE_N
            and same_source["lambda3"] != 0.05
            and same_source["score_delta_log_loss"] <= -MIN_SCORE_LOGLOSS_GAIN
            and same_source["ou_non_regression_passed"]
            and same_source["paired_ci_supports_full_candidate"]):
        score = {"decision": "review_required", "reason": "same_source_time_split_score_and_ou_passed",
                 "n": same_source["test_n"], "lambda3": same_source["lambda3"],
                 "observed_delta": same_source["score_delta_log_loss"]}
    elif (same_source is not None and same_source["test_n"] >= MIN_SCORE_N
          and same_source["lambda3"] != 0.05
          and same_source["score_delta_log_loss"] <= -MIN_SCORE_LOGLOSS_GAIN
          and same_source["ou_non_regression_passed"]):
        score = _hold("paired_ci_not_decisive_for_all_affected_outputs", n=same_source["test_n"],
                      lambda3=same_source["lambda3"], observed_delta=same_source["score_delta_log_loss"])
    elif score_n < MIN_SCORE_N:
        score = _hold("same_family_oos_sample_below_minimum", n=score_n, minimum_n=MIN_SCORE_N)
    elif not isinstance(delta, (int, float)) or delta > -MIN_SCORE_LOGLOSS_GAIN:
        score = _hold("shadow_log_loss_gain_not_large_enough", n=score_n,
                      required_delta_at_most=-MIN_SCORE_LOGLOSS_GAIN, observed_delta=delta)
    else:
        score = {"decision": "review_required", "reason": "shadow_threshold_met_manual_release_required",
                 "n": score_n, "observed_delta": delta}

    ou25, ou35 = derivatives.get("ou_2_5", {}), derivatives.get("ou_3_5", {})
    ou_n = min(int(ou25.get("n") or 0), int(ou35.get("n") or 0))
    if (same_source is not None and same_source["ou_n"] >= MIN_OU_N
            and same_source["ou_non_regression_passed"]
            and same_source["paired_ci_supports_full_candidate"]):
        ou = {"decision": "review_required", "reason": "same_source_lambda3_ou_non_regression_passed",
              "n": same_source["ou_n"], "minimum_n": MIN_OU_N}
    elif (same_source is not None and same_source["ou_n"] >= MIN_OU_N
          and same_source["ou_non_regression_passed"]):
        ou = _hold("paired_ci_not_decisive_for_all_affected_outputs", n=same_source["ou_n"],
                   minimum_n=MIN_OU_N)
    else:
        ou = (_hold("both_ou_lines_need_same_family_samples", n=ou_n, minimum_n=MIN_OU_N,
                ou_2_5_n=int(ou25.get("n") or 0), ou_3_5_n=int(ou35.get("n") or 0))
          if ou_n < MIN_OU_N else
          {"decision": "review_required", "reason": "sample_threshold_met_comparator_required",
           "n": ou_n, "minimum_n": MIN_OU_N})

    hafu = derivatives.get("hafu", {})
    hafu_n = int(hafu.get("n") or 0)
    unfit = int(hafu.get("excluded_unfitted_prediction") or 0)
    if unfit:
        hafu_decision = _hold("hafu_predictions_unfitted", n=hafu_n,
                              excluded_unfitted_prediction=unfit, minimum_n=MIN_HAFU_N)
    elif hafu_n < MIN_HAFU_N:
        hafu_decision = _hold("verified_hafu_sample_below_minimum", n=hafu_n, minimum_n=MIN_HAFU_N)
    else:
        hafu_decision = {"decision": "review_required", "reason": "verified_sample_threshold_met_comparator_required",
                         "n": hafu_n, "minimum_n": MIN_HAFU_N}

    families = {"wdl": wdl, "score": score, "ou": ou, "hafu": hafu_decision}
    return {
        "schema": "four-market-admission-1.0",
        "research_only": True,
        "production_change_allowed": False,
        "families": families,
        "note": ("review_required 也不是自动上线；任何概率变化仍须版本升级、独立复核与发布锁。"
                 "当前脚本不会写入生产配置。"),
    }


def _read(path: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="四类输出参数变更准入；仅报告，不修改生产")
    parser.add_argument("--backtest", required=True)
    parser.add_argument("--derivatives", required=True)
    parser.add_argument("--score-shadow", required=True)
    parser.add_argument("--score-time-split", help="体彩同源lambda3时间切分研究报告")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    backtest = _read(args.backtest)
    derivatives_raw = _read(args.derivatives)
    derivatives = derivatives_raw.get("metrics", derivatives_raw)
    score_time_split = _read(args.score_time_split) if args.score_time_split else None
    report = admission_report(backtest, derivatives, _read(args.score_shadow), score_time_split)
    report["inputs"] = {"backtest": args.backtest, "derivatives": args.derivatives,
                        "score_shadow": args.score_shadow, "score_time_split": args.score_time_split}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(target), "families": report["families"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
