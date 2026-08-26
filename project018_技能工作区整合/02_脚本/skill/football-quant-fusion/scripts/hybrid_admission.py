#!/usr/bin/env python3
"""只读 hybrid 上线资格门禁；绝不改变生产推荐开关。"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hybrid_contract import LIVE_HYBRID_REVIEW_UNIQUE


def _parse_time(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _paired_ci(values: list[float], samples: int, seed: int) -> list[float] | None:
    if not values or samples <= 0:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    return [means[int(0.025 * (samples - 1))], means[math.ceil(0.975 * (samples - 1))]]


def _chronological_date_split(rows: list[dict], ratio: float = 0.70) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda row: _parse_time(row["kickoff"]))
    by_day: dict[str, list[dict]] = {}
    for row in ordered:
        by_day.setdefault(_parse_time(row["kickoff"]).date().isoformat(), []).append(row)
    days = list(by_day)
    target = len(ordered) * ratio
    cumulative = 0
    boundary = 1
    best_distance = float("inf")
    for index in range(1, len(days)):
        cumulative += len(by_day[days[index - 1]])
        distance = abs(cumulative - target)
        if distance < best_distance:
            best_distance = distance
            boundary = index
    train = [row for day in days[:boundary] for row in by_day[day]]
    test = [row for day in days[boundary:] for row in by_day[day]]
    return train, test


def review_protocol(rows: list[dict], *, minimum_n: int = 100,
                    bootstrap_samples: int = 10000, bootstrap_seed: int = 20260826,
                    denominator_id: str = LIVE_HYBRID_REVIEW_UNIQUE) -> dict:
    """Frozen n=100 protocol; it grants review eligibility, never production."""
    base = {
        "schema_version": "hybrid-review-decision-1.0",
        "denominator_id": denominator_id,
        "n": len(rows),
        "minimum_n": minimum_n,
        "automatic_production_change": False,
        "production_recommendations_enabled": False,
    }
    if len(rows) < minimum_n:
        return {**base, "decision": "INSUFFICIENT_SAMPLE", "split": None, "test": None}
    train, test = _chronological_date_split(rows)
    brier = [float(row["brier_delta_hybrid_minus_market"]) for row in test]
    logloss = [float(row["logloss_delta_hybrid_minus_market"]) for row in test]
    brier_ci = _paired_ci(brier, bootstrap_samples, bootstrap_seed)
    logloss_ci = _paired_ci(logloss, bootstrap_samples, bootstrap_seed)
    metrics = {
        "brier": {"mean_delta_hybrid_minus_market": sum(brier) / len(brier),
                  "paired_bootstrap_95_ci": brier_ci},
        "logloss": {"mean_delta_hybrid_minus_market": sum(logloss) / len(logloss),
                    "paired_bootstrap_95_ci": logloss_ci},
    }
    if ((brier_ci and brier_ci[0] > 0) or (logloss_ci and logloss_ci[0] > 0)):
        decision = "EVIDENCE_OF_HARM"
    elif brier_ci and logloss_ci and brier_ci[1] < 0 and logloss_ci[1] < 0:
        decision = "EVIDENCE_BETTER_THAN_MARKET"
    else:
        decision = "NO_EVIDENCE"
    return {
        **base,
        "decision": decision,
        "split": {
            "method": "chronological_70_30_by_kickoff_date_group",
            "train_n": len(train),
            "test_n": len(test),
            "train_through": max(_parse_time(row["kickoff"]) for row in train).isoformat(),
            "test_from": min(_parse_time(row["kickoff"]) for row in test).isoformat(),
        },
        "bootstrap": {"samples": bootstrap_samples, "seed": bootstrap_seed, "paired_by": "match_id"},
        "test": metrics,
    }


def admission_report(evaluation: dict, *, minimum_n: int = 100) -> dict:
    reasons = []
    if int(evaluation.get("n") or 0) < minimum_n:
        reasons.append("insufficient_sample")
    metrics = evaluation.get("metrics") or {}
    for name in ("brier", "logloss"):
        metric = metrics.get(name) or {}
        delta = metric.get("delta_hybrid_minus_market")
        ci = metric.get("paired_bootstrap_95_ci")
        if not isinstance(delta, (int, float)) or delta >= 0:
            reasons.append(f"{name}_not_better_than_market")
        if not isinstance(ci, list) or len(ci) != 2 or not all(isinstance(x, (int, float)) for x in ci):
            reasons.append(f"{name}_ci_unavailable")
        elif ci[1] >= 0:
            reasons.append(f"{name}_ci_not_strictly_below_zero")
    return {
        "schema_version": "hybrid-admission-1.0",
        "research_only": True,
        "evaluation_n": int(evaluation.get("n") or 0),
        "minimum_n": minimum_n,
        "status": "BLOCKED" if reasons else "ELIGIBLE_FOR_HUMAN_REVIEW",
        "reasons": reasons,
        "automatic_production_change": False,
        "production_recommendations_enabled": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="hybrid 生产融合资格门禁（只读）")
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--minimum-n", type=int, default=100)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    evaluation = json.loads(Path(args.evaluation).read_text(encoding="utf-8"))
    report = admission_report(evaluation, minimum_n=args.minimum_n)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
