#!/usr/bin/env python3
"""Current-version review gate; never changes weights or production recommendations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _strictly_below_zero(value) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(
        isinstance(item, (int, float)) for item in value) and value[1] < 0


def admission_report(backtest: dict, *, minimum_n: int = 100, minimum_league_n: int = 300) -> dict:
    gate = backtest.get("calibration_gate") or {}
    current_n = int(gate.get("current_version_n") or 0)
    paired = backtest.get("current_paired_market")
    reasons: list[str] = []
    if not isinstance(paired, dict):
        paired = {}
        reasons.append("current_paired_market_missing")
    paired_n = int(paired.get("n") or 0)
    if current_n < minimum_n:
        reasons.append("current_sample_below_minimum")
    if paired_n < minimum_n:
        reasons.append("paired_market_sample_below_minimum")
    checks = (
        ("brier", paired.get("brier_delta_model_minus_market"), paired.get("brier_delta_95ci")),
        ("logloss", paired.get("log_loss_delta_model_minus_market"), paired.get("log_loss_delta_95ci")),
    )
    for name, delta, interval in checks:
        if not isinstance(delta, (int, float)) or delta >= 0:
            reasons.append(f"{name}_not_better_than_market")
        if not _strictly_below_zero(interval):
            reasons.append(f"{name}_ci_not_strictly_below_zero")

    league_review = {}
    for league, metrics in sorted((backtest.get("current_by_league") or {}).items()):
        n = int((metrics or {}).get("n") or 0)
        league_review[str(league)] = {
            "n": n,
            "minimum_n": minimum_league_n,
            "status": "READY_FOR_DESCRIPTIVE_REVIEW" if n >= minimum_league_n else "INSUFFICIENT",
        }
    return {
        "schema_version": "fusion-version-admission-1.0",
        "current_identity": backtest.get("current_identity") or {},
        "current_version_n": current_n,
        "paired_market_n": paired_n,
        "minimum_n": minimum_n,
        "status": "HOLD" if reasons else "ELIGIBLE_FOR_HUMAN_REVIEW",
        "reasons": reasons,
        "paired_market": paired,
        "league_review": league_review,
        "automatic_weight_change": False,
        "production_recommendations_enabled": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest", required=True)
    parser.add_argument("--minimum-n", type=int, default=100)
    parser.add_argument("--minimum-league-n", type=int, default=300)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    backtest = json.loads(Path(args.backtest).read_text(encoding="utf-8-sig"))
    report = admission_report(backtest, minimum_n=args.minimum_n,
                              minimum_league_n=args.minimum_league_n)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
